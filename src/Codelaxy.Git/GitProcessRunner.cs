using System.ComponentModel;
using System.Diagnostics;

namespace Codelaxy.Git;

public sealed class GitProcessRunner
{
    private readonly string _gitExecutable;

    public GitProcessRunner(string gitExecutable = "git")
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(gitExecutable);

        _gitExecutable = gitExecutable;
    }

    public Task<GitCommandResult> RunAsync(
    string workingDirectory,
    IEnumerable<string> arguments,
    CancellationToken cancellationToken = default)
    {
        return RunCoreAsync(
            workingDirectory,
            arguments,
            readOnly: false,
            timeout: null,
            cancellationToken);
    }

public Task<GitCommandResult> RunReadOnlyAsync(
    string workingDirectory,
    IEnumerable<string> arguments,
    CancellationToken cancellationToken = default)
{
    return RunCoreAsync(
        workingDirectory,
        arguments,
        readOnly: true,
        timeout: null,
        cancellationToken);
}
    public Task<GitCommandResult> RunAsync(
    string workingDirectory,
    IEnumerable<string> arguments,
    TimeSpan timeout,
    CancellationToken cancellationToken = default)
    {
        if (timeout <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(timeout),
                "Timeout must be greater than zero.");
        }

        return RunCoreAsync(
            workingDirectory,
            arguments,
            readOnly: false,
            timeout,
            cancellationToken);
    }

private async Task<GitCommandResult> RunCoreAsync(
    string workingDirectory,
    IEnumerable<string> arguments,
    bool readOnly,
    TimeSpan? timeout,
    CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(workingDirectory);
        ArgumentNullException.ThrowIfNull(arguments);

        cancellationToken.ThrowIfCancellationRequested();

        var startInfo = new ProcessStartInfo
        {
            FileName = _gitExecutable,
            WorkingDirectory = workingDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        startInfo.Environment.Remove("GIT_DIR");
        startInfo.Environment.Remove("GIT_WORK_TREE");
        startInfo.Environment.Remove("GIT_INDEX_FILE");

        if (readOnly)
{
    startInfo.Environment["GIT_OPTIONAL_LOCKS"] = "0";
}

        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process
        {
            StartInfo = startInfo,
        };

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
                GitCommandFailureKind.LaunchFailure);
        }

        var standardOutputTask =
            process.StandardOutput.ReadToEndAsync();

        var standardErrorTask =
            process.StandardError.ReadToEndAsync();

        using var timeoutCancellation =
            timeout.HasValue
                ? new CancellationTokenSource(timeout.Value)
                : null;

        using var waitCancellation =
            timeoutCancellation is not null
                ? CancellationTokenSource.CreateLinkedTokenSource(
                    cancellationToken,
                    timeoutCancellation.Token)
                : null;

        var waitToken =
            waitCancellation?.Token ??
            cancellationToken;

        try
        {
            await process.WaitForExitAsync(waitToken);
        }
        catch (OperationCanceledException)
            when (waitToken.IsCancellationRequested)
        {
            await TerminateProcessTreeAsync(process);

            await Task.WhenAll(
                standardOutputTask,
                standardErrorTask);

            if (cancellationToken.IsCancellationRequested)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }

            if (timeoutCancellation?.IsCancellationRequested == true)
            {
                return new GitCommandResult(
                    process.ExitCode,
                    await standardOutputTask,
                    await standardErrorTask,
                    GitCommandFailureKind.Timeout);
            }

            throw;
        }

        var standardOutput =
            await standardOutputTask;

        var standardError =
            await standardErrorTask;

        return new GitCommandResult(
            process.ExitCode,
            standardOutput,
            standardError);
    }

    private static async Task TerminateProcessTreeAsync(
        Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(
                    entireProcessTree: true);
            }
        }
        catch (InvalidOperationException)
        {
            // The process exited between HasExited and Kill.
        }

        await process.WaitForExitAsync();
    }
}