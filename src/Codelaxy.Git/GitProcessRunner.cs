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

    public async Task<GitCommandResult> RunAsync(
        string workingDirectory,
        IEnumerable<string> arguments,
        CancellationToken cancellationToken = default)
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

try
{
    await process.WaitForExitAsync(cancellationToken);
}
catch (OperationCanceledException)
    when (cancellationToken.IsCancellationRequested)
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

    await Task.WhenAll(
        standardOutputTask,
        standardErrorTask);

    throw;
}

        var standardOutput = await standardOutputTask;
        var standardError = await standardErrorTask;

        return new GitCommandResult(
            process.ExitCode,
            standardOutput,
            standardError);
    }
}
