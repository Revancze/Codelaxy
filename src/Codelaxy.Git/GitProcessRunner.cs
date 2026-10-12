using System.ComponentModel;
using System.Diagnostics;
using System.Text;

namespace Codelaxy.Git;

public sealed class GitProcessRunner
{
    private static readonly string[] RepositoryLocalEnvironmentVariables =
    [
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_OBJECT_DIRECTORY",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_REPLACE_REF_BASE",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_COMMON_DIR",
        "GIT_CEILING_DIRECTORIES",
    ];

    private static readonly UTF8Encoding StrictUtf8 = new(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: true
    );

    private static readonly UTF8Encoding DiagnosticUtf8 = new(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: false
    );

    // The MSYS2 root used to interpret POSIX paths in Git metadata (Windows only).
    internal const string GitEnvironmentRootVariable = "CODELAXY_GIT_ENVIRONMENT_ROOT";

    private readonly string? _gitExecutable;
    private readonly string? _gitResolutionDiagnostic;
    private readonly bool _gitExecutableResolvedFromPath;

    // Shared by the PATH resolver and the launch guard. Never authorizes on its own.
    private readonly PosixMountTable? _posixMounts;

    public GitProcessRunner()
        : this(
            Environment.GetEnvironmentVariable("PATH"),
            Environment.CurrentDirectory,
            Environment.GetEnvironmentVariable(GitEnvironmentRootVariable)
        ) { }

    internal GitProcessRunner(string? pathVariable, string currentDirectory)
        : this(pathVariable, currentDirectory, gitEnvironmentRoot: null) { }

    // gitEnvironmentRoot: the explicitly configured MSYS2 root, or null/empty when
    // none is configured. An unusable value refuses every command; PATH is then not
    // searched, so there is no fallback to running as if nothing were configured.
    internal GitProcessRunner(
        string? pathVariable,
        string currentDirectory,
        string? gitEnvironmentRoot
    )
    {
        _gitExecutableResolvedFromPath = true;

        if (!string.IsNullOrEmpty(gitEnvironmentRoot))
        {
            _posixMounts = PosixMountTable.TryLoad(gitEnvironmentRoot, out var problem);

            if (_posixMounts is null)
            {
                _gitResolutionDiagnostic =
                    $"{GitEnvironmentRootVariable} '{gitEnvironmentRoot}' is not a usable "
                    + $"MSYS2 environment root: {problem}. Git was not searched on PATH.";

                return;
            }
        }

        _gitExecutable = ResolveDefaultGitExecutable(
            pathVariable,
            currentDirectory,
            _posixMounts,
            out var refusal
        );

        if (_gitExecutable is null)
        {
            _gitResolutionDiagnostic =
                refusal ?? "Unable to locate Git executable in trusted absolute PATH entries.";
        }
    }

    public GitProcessRunner(string gitExecutable)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(gitExecutable);

        _gitExecutable = gitExecutable;
    }

    public Task<GitCommandResult> RunAsync(
        string workingDirectory,
        IEnumerable<string> arguments,
        CancellationToken cancellationToken = default
    )
    {
        return RunCoreAsync(
            workingDirectory,
            arguments,
            readOnly: false,
            timeout: null,
            standardInput: null,
            cancellationToken
        );
    }

    public Task<GitCommandResult> RunAsync(
        string workingDirectory,
        IEnumerable<string> arguments,
        TimeSpan timeout,
        CancellationToken cancellationToken = default
    )
    {
        if (timeout <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(timeout),
                "Timeout must be greater than zero."
            );
        }

        return RunCoreAsync(
            workingDirectory,
            arguments,
            readOnly: false,
            timeout,
            standardInput: null,
            cancellationToken
        );
    }

    public Task<GitCommandResult> RunReadOnlyAsync(
        string workingDirectory,
        IEnumerable<string> arguments,
        TimeSpan timeout,
        CancellationToken cancellationToken = default
    )
    {
        if (timeout <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(timeout),
                "Timeout must be greater than zero."
            );
        }

        return RunCoreAsync(
            workingDirectory,
            arguments,
            readOnly: true,
            timeout,
            standardInput: null,
            cancellationToken
        );
    }

    public Task<GitCommandResult> RunReadOnlyAsync(
        string workingDirectory,
        IEnumerable<string> arguments,
        TimeSpan timeout,
        byte[] standardInput,
        CancellationToken cancellationToken = default
    )
    {
        ArgumentNullException.ThrowIfNull(standardInput);

        if (timeout <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(timeout),
                "Timeout must be greater than zero."
            );
        }

        return RunCoreAsync(
            workingDirectory,
            arguments,
            readOnly: true,
            timeout,
            standardInput,
            cancellationToken
        );
    }

    private async Task<GitCommandResult> RunCoreAsync(
        string workingDirectory,
        IEnumerable<string> arguments,
        bool readOnly,
        TimeSpan? timeout,
        byte[]? standardInput,
        CancellationToken cancellationToken
    )
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(workingDirectory);
        ArgumentNullException.ThrowIfNull(arguments);

        cancellationToken.ThrowIfCancellationRequested();

        if (_gitExecutable is null)
        {
            return new GitCommandResult(
                null,
                string.Empty,
                _gitResolutionDiagnostic ?? "Unable to locate Git executable.",
                GitCommandFailureKind.LaunchFailure
            );
        }

        // A PATH-resolved executable must be verified again against the
        // repository targeted by this command.
        if (_gitExecutableResolvedFromPath)
        {
            var refusal = GetGitLaunchRefusalDiagnostic(_gitExecutable, workingDirectory);

            if (refusal is not null)
            {
                return new GitCommandResult(
                    null,
                    string.Empty,
                    refusal,
                    GitCommandFailureKind.LaunchFailure
                );
            }
        }

        var startInfo = CreateProcessStartInfo(workingDirectory, arguments, readOnly);

        using var process = new Process { StartInfo = startInfo };

        try
        {
            process.Start();
        }
        catch (Win32Exception exception)
        {
            return new GitCommandResult(
                null,
                string.Empty,
                exception.Message,
                GitCommandFailureKind.LaunchFailure
            );
        }

        var standardOutputTask = ReadAllBytesAsync(process.StandardOutput.BaseStream);
        var standardErrorTask = ReadAllBytesAsync(process.StandardError.BaseStream);

        using var timeoutCancellation = timeout.HasValue
            ? new CancellationTokenSource(timeout.Value)
            : null;

        using var waitCancellation = timeoutCancellation is not null
            ? CancellationTokenSource.CreateLinkedTokenSource(
                cancellationToken,
                timeoutCancellation.Token
            )
            : null;

        var waitToken = waitCancellation?.Token ?? cancellationToken;

        try
        {
            if (standardInput is null)
            {
                process.StandardInput.Close();
            }
            else
            {
                await process.StandardInput.BaseStream.WriteAsync(
                    standardInput.AsMemory(),
                    waitToken
                );

                await process.StandardInput.BaseStream.FlushAsync(waitToken);

                process.StandardInput.Close();
            }

            await process.WaitForExitAsync(waitToken);
        }
        catch (OperationCanceledException) when (waitToken.IsCancellationRequested)
        {
            await TerminateProcessTreeAsync(process);

            await Task.WhenAll(standardOutputTask, standardErrorTask);

            if (cancellationToken.IsCancellationRequested)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }

            if (timeoutCancellation?.IsCancellationRequested == true)
            {
                return CreateResult(
                    process.ExitCode,
                    await standardOutputTask,
                    await standardErrorTask,
                    GitCommandFailureKind.Timeout
                );
            }

            throw;
        }

        return CreateResult(
            process.ExitCode,
            await standardOutputTask,
            await standardErrorTask,
            GitCommandFailureKind.None
        );
    }

    private string? GetGitLaunchRefusalDiagnostic(string gitExecutable, string workingDirectory)
    {
        if (!OperatingSystem.IsWindows())
        {
            return RepositoryControlledPaths.IsInsideAny(
                gitExecutable,
                RepositoryControlledPaths.GetProtectedRoots(workingDirectory)
            )
                ? $"Refusing to run Git '{gitExecutable}' from inside the repository "
                    + $"being observed at '{workingDirectory}'."
                : null;
        }

        return GetWindowsLocationRefusal(gitExecutable, workingDirectory, _posixMounts);
    }

    // The one Windows location check: the PATH resolver and the launch guard ask the
    // same question with the same environment and word the answer the same way.
    private static string? GetWindowsLocationRefusal(
        string gitExecutable,
        string directory,
        PosixMountTable? posixMounts
    )
    {
        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            gitExecutable,
            directory,
            posixMounts
        );

        if (decision.Verdict == GitExecutableLocationVerifier.Verdict.Allow)
        {
            return null;
        }

        if (decision.Verdict == GitExecutableLocationVerifier.Verdict.Deny)
        {
            return $"Refusing to run Git '{gitExecutable}' from inside the repository "
                + $"being observed at '{directory}'.";
        }

        var refusal =
            $"Refusing to run Git '{gitExecutable}' for '{directory}': "
            + $"unable to verify executable location ({decision.Reason}).";

        var environmentRoot = posixMounts?.Root;

        return decision.Reason switch
        {
            GitExecutableLocationVerifier.Reason.UnmappedPosixMetadata => refusal
                + " Its Git metadata uses MSYS2/Cygwin POSIX paths; set "
                + $"{GitEnvironmentRootVariable} to the MSYS2 root (in an MSYS2 shell: "
                + $"export {GitEnvironmentRootVariable}=\"$(cygpath -w /)\").",

            GitExecutableLocationVerifier.Reason.UnprovenPosixMetadata => refusal
                + $" Its Git metadata could not be proven under {GitEnvironmentRootVariable} "
                + $"'{environmentRoot}'.",

            GitExecutableLocationVerifier.Reason.PosixEnvironmentMismatch => refusal
                + $" Only '{environmentRoot}\\usr\\bin\\git.exe' from "
                + $"{GitEnvironmentRootVariable} reads its metadata the same way.",

            GitExecutableLocationVerifier.Reason.UntrustedPosixEnvironment => refusal
                + $" {GitEnvironmentRootVariable} '{environmentRoot}' lies inside "
                + "a repository-controlled directory.",

            _ => refusal,
        };
    }

    // Git output is read as raw bytes and decoded afterwards. A StreamReader
    // would honour a byte order mark at the start of the output (dropping it,
    // or switching to UTF-16), and a throwing decoder inside it would stop
    // draining the pipe while Git is still writing.
    private static async Task<byte[]> ReadAllBytesAsync(Stream stream)
    {
        await using var buffer = new MemoryStream();

        await stream.CopyToAsync(buffer);

        return buffer.ToArray();
    }

    // Standard output feeds observations and must decode exactly; standard
    // error is diagnostics only and keeps replacement characters.
    private static GitCommandResult CreateResult(
        int exitCode,
        byte[] standardOutput,
        byte[] standardError,
        GitCommandFailureKind failureKind
    )
    {
        var diagnostic = DiagnosticUtf8.GetString(standardError);

        try
        {
            return new GitCommandResult(
                exitCode,
                StrictUtf8.GetString(standardOutput),
                diagnostic,
                failureKind
            );
        }
        catch (DecoderFallbackException)
        {
            return new GitCommandResult(
                exitCode,
                string.Empty,
                ("Git output is not valid UTF-8. " + diagnostic).TrimEnd(),
                failureKind == GitCommandFailureKind.None
                    ? GitCommandFailureKind.InvalidOutput
                    : failureKind
            );
        }
    }

    internal ProcessStartInfo CreateProcessStartInfo(
        string workingDirectory,
        IEnumerable<string> arguments,
        bool readOnly
    )
    {
        if (_gitExecutable is null)
        {
            throw new InvalidOperationException("Git executable has not been resolved.");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = _gitExecutable,
            WorkingDirectory = workingDirectory,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = StrictUtf8,
            StandardErrorEncoding = DiagnosticUtf8,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        RemoveInheritedGitEnvironment(startInfo);

        startInfo.Environment["GIT_TERMINAL_PROMPT"] = "0";

        if (readOnly)
        {
            startInfo.Environment["GIT_OPTIONAL_LOCKS"] = "0";

            startInfo.Environment["GIT_CONFIG_COUNT"] = "1";
            startInfo.Environment["GIT_CONFIG_KEY_0"] = "core.fsmonitor";
            startInfo.Environment["GIT_CONFIG_VALUE_0"] = "false";
        }

        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        return startInfo;
    }

    private static void RemoveInheritedGitEnvironment(ProcessStartInfo startInfo)
    {
        foreach (var variableName in RepositoryLocalEnvironmentVariables)
        {
            startInfo.Environment.Remove(variableName);
        }

        startInfo.Environment.Remove("GIT_CONFIG_GLOBAL");
        startInfo.Environment.Remove("GIT_CONFIG_SYSTEM");
        startInfo.Environment.Remove("GIT_CONFIG_NOSYSTEM");

        var inheritedVariables = startInfo.Environment.Keys.ToArray();

        foreach (var variableName in inheritedVariables)
        {
            if (
                variableName.StartsWith("GIT_CONFIG_KEY_", StringComparison.OrdinalIgnoreCase)
                || variableName.StartsWith("GIT_CONFIG_VALUE_", StringComparison.OrdinalIgnoreCase)
            )
            {
                startInfo.Environment.Remove(variableName);
            }
        }
    }

    internal static string? ResolveDefaultGitExecutable(
        string? pathVariable,
        string currentDirectory
    )
    {
        return ResolveDefaultGitExecutable(
            pathVariable,
            currentDirectory,
            posixMounts: null,
            out _
        );
    }

    // refusal: on Windows, why the first Git found on PATH was not accepted.
    internal static string? ResolveDefaultGitExecutable(
        string? pathVariable,
        string currentDirectory,
        PosixMountTable? posixMounts,
        out string? refusal
    )
    {
        refusal = null;

        ArgumentException.ThrowIfNullOrWhiteSpace(currentDirectory);

        var executableName = OperatingSystem.IsWindows() ? "git.exe" : "git";

        if (string.IsNullOrEmpty(pathVariable))
        {
            return null;
        }

        var absoluteCurrentDirectory = Path.GetFullPath(currentDirectory);

        var protectedRoots = RepositoryControlledPaths.GetProtectedRoots(absoluteCurrentDirectory);

        var pathComparison = OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;

        foreach (var rawDirectory in pathVariable.Split(Path.PathSeparator))
        {
            if (rawDirectory.Length == 0)
            {
                continue;
            }

            var directory = rawDirectory;

            if (directory.Length >= 2 && directory[0] == '"' && directory[^1] == '"')
            {
                directory = directory[1..^1];
            }

            if (!Path.IsPathFullyQualified(directory))
            {
                continue;
            }

            string fullDirectory;

            try
            {
                fullDirectory = Path.GetFullPath(directory);
            }
            catch (ArgumentException)
            {
                continue;
            }
            catch (NotSupportedException)
            {
                continue;
            }

            if (
                string.Equals(
                    fullDirectory.TrimEnd(
                        Path.DirectorySeparatorChar,
                        Path.AltDirectorySeparatorChar
                    ),
                    absoluteCurrentDirectory.TrimEnd(
                        Path.DirectorySeparatorChar,
                        Path.AltDirectorySeparatorChar
                    ),
                    pathComparison
                )
            )
            {
                continue;
            }

            if (
                !OperatingSystem.IsWindows()
                && RepositoryControlledPaths.IsInsideAny(fullDirectory, protectedRoots)
            )
            {
                continue;
            }

            var candidate = Path.Combine(fullDirectory, executableName);

            if (!File.Exists(candidate))
            {
                continue;
            }

            // On Windows the same check, with the same environment, as the launch guard.
            var windowsRefusal = OperatingSystem.IsWindows()
                ? GetWindowsLocationRefusal(candidate, absoluteCurrentDirectory, posixMounts)
                : null;

            var trusted = OperatingSystem.IsWindows()
                ? windowsRefusal is null
                : !RepositoryControlledPaths.IsInsideAny(candidate, protectedRoots);

            if (trusted)
            {
                return Path.GetFullPath(candidate);
            }

            refusal ??= windowsRefusal;
        }

        return null;
    }

    private static async Task TerminateProcessTreeAsync(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException)
        {
            // The process exited between HasExited and Kill.
        }

        await process.WaitForExitAsync();
    }
}
