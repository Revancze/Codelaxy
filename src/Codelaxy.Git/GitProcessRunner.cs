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

    private readonly string? _gitExecutable;
    private readonly string? _gitResolutionDiagnostic;
    private readonly bool _gitExecutableResolvedFromPath;

    public GitProcessRunner()
        : this(Environment.GetEnvironmentVariable("PATH"), Environment.CurrentDirectory) { }

    internal GitProcessRunner(string? pathVariable, string currentDirectory)
    {
        _gitExecutable = ResolveDefaultGitExecutable(pathVariable, currentDirectory);
        _gitExecutableResolvedFromPath = true;

        if (_gitExecutable is null)
        {
            _gitResolutionDiagnostic =
                "Unable to locate Git executable in trusted absolute PATH entries.";
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

        // The executable was chosen relative to the directory the runner was
        // created in; a command may target a different repository.
        if (
            _gitExecutableResolvedFromPath
            && RepositoryControlledPaths.IsInsideAny(
                _gitExecutable,
                RepositoryControlledPaths.GetProtectedRoots(workingDirectory)
            )
        )
        {
            return new GitCommandResult(
                null,
                string.Empty,
                $"Refusing to run Git '{_gitExecutable}' from inside the repository "
                    + $"being observed at '{workingDirectory}'.",
                GitCommandFailureKind.LaunchFailure
            );
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

            var trusted = OperatingSystem.IsWindows()
                ? GitExecutableLocationVerifier.Verify(candidate, absoluteCurrentDirectory)
                    == GitExecutableLocationVerifier.Verdict.Allow
                : !RepositoryControlledPaths.IsInsideAny(candidate, protectedRoots);

            if (trusted)
            {
                return Path.GetFullPath(candidate);
            }
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
