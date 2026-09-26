using Codelaxy.Git;
using System.Diagnostics;

namespace Codelaxy.Tests;

public class GitProcessRunnerTests
{
    [Fact]
    public async Task RunAsync_CanExecuteGit()
    {
        var runner = new GitProcessRunner();

        var result = await runner.RunAsync(
            Directory.GetCurrentDirectory(),
            ["--version"]);

        Assert.True(result.Succeeded);
        Assert.Equal(0, result.ExitCode);
        Assert.StartsWith("git version ", result.StandardOutput);
        Assert.True(string.IsNullOrWhiteSpace(result.StandardError));
    }

    [Fact]
    public async Task RunAsync_UsesRequestedWorkingDirectory()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(
                repositoryPath,
                ["init"]);

            Assert.True(initResult.Succeeded);

            var nestedPath = Path.Combine(
                repositoryPath,
                "directory with spaces");

            Directory.CreateDirectory(nestedPath);

            var result = await runner.RunAsync(
                nestedPath,
                ["rev-parse", "--show-prefix"]);

            Assert.True(result.Succeeded);

            var actualPrefix =
                result.StandardOutput.Trim().Replace('\\', '/');

            Assert.Equal(
                "directory with spaces/",
                actualPrefix);
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
        }
    }

    [Fact]
    public async Task RunAsync_PreservesArgumentContainingSpaces()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(
                repositoryPath,
                ["init"]);

            Assert.True(initResult.Succeeded);

            var setResult = await runner.RunAsync(
                repositoryPath,
                [
                    "config",
                    "--local",
                    "codelaxy.test",
                    "value with spaces"
                ]);

            Assert.True(setResult.Succeeded);

            var getResult = await runner.RunAsync(
                repositoryPath,
                [
                    "config",
                    "--local",
                    "--get",
                    "codelaxy.test"
                ]);

            Assert.True(getResult.Succeeded);

            Assert.Equal(
                "value with spaces",
                getResult.StandardOutput.Trim());
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
        }
    }

    [Fact]
    public async Task RunAsync_ReturnsFailureWithoutThrowing()
    {
        var runner = new GitProcessRunner();

        var result = await runner.RunAsync(
            Directory.GetCurrentDirectory(),
            ["codelaxy-command-that-does-not-exist"]);

        Assert.False(result.Succeeded);
        Assert.NotEqual(0, result.ExitCode);
        Assert.False(string.IsNullOrWhiteSpace(result.StandardError));
    }

    [Fact]
    public async Task RunAsync_ReturnsLaunchFailureWhenGitCannotBeStarted()
    {
        var runner = new GitProcessRunner(
            "codelaxy-git-executable-that-does-not-exist");

        var result = await runner.RunAsync(
            Directory.GetCurrentDirectory(),
            ["--version"]);

        Assert.False(result.Started);
        Assert.Null(result.ExitCode);
        Assert.Equal(
            GitCommandFailureKind.LaunchFailure,
            result.FailureKind);
        Assert.False(result.Succeeded);
    }

       [Fact]
    public async Task RunAsync_DoesNotStartProcessWhenAlreadyCancelled()
    {
        var runner = new GitProcessRunner(
            "codelaxy-git-executable-that-does-not-exist");

        using var cancellation =
            new CancellationTokenSource();

        cancellation.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => runner.RunAsync(
                Directory.GetCurrentDirectory(),
                ["--version"],
                cancellation.Token));
    }

        [Fact]
    public async Task RunAsync_KillsStartedProcessWhenCancelled()
    {
        var runner = new GitProcessRunner("dotnet");

        var testOutputDirectory =
            new DirectoryInfo(AppContext.BaseDirectory);

        var targetFramework =
            testOutputDirectory.Name;

        var configuration =
            testOutputDirectory.Parent!.Name;

        var testsDirectory =
            testOutputDirectory
                .Parent!
                .Parent!
                .Parent!
                .Parent!;

        var helperPath = Path.Combine(
            testsDirectory.FullName,
            "Codelaxy.ProcessTestHelper",
            "bin",
            configuration,
            targetFramework,
            "Codelaxy.ProcessTestHelper.dll");

        Assert.True(
            File.Exists(helperPath),
            $"Process test helper not found: {helperPath}");

        var pidFile = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Process {Guid.NewGuid():N}.pid");

        using var cancellation =
            new CancellationTokenSource();

        Process? helperProcess = null;

        try
        {
            var runTask = runner.RunAsync(
                Directory.GetCurrentDirectory(),
                [helperPath, pidFile],
                cancellation.Token);

            using var startTimeout =
                new CancellationTokenSource(
                    TimeSpan.FromSeconds(10));

            while (!File.Exists(pidFile))
            {
                await Task.Delay(
                    20,
                    startTimeout.Token);
            }

            var processId = int.Parse(
                await File.ReadAllTextAsync(
                    pidFile,
                    startTimeout.Token));

            helperProcess =
                Process.GetProcessById(processId);

            cancellation.Cancel();

            await Assert.ThrowsAnyAsync<OperationCanceledException>(
                () => runTask);

            var exitTask =
                helperProcess.WaitForExitAsync();

            var completedTask =
                await Task.WhenAny(
                    exitTask,
                    Task.Delay(TimeSpan.FromSeconds(2)));

            Assert.Same(
                exitTask,
                completedTask);
        }
        finally
        {
            cancellation.Cancel();

            if (helperProcess is not null)
            {
                try
                {
                    if (!helperProcess.HasExited)
                    {
                        helperProcess.Kill(
                            entireProcessTree: true);

                        await helperProcess.WaitForExitAsync();
                    }
                }
                catch (InvalidOperationException)
                {
                    // Process exited between HasExited and Kill.
                }

                helperProcess.Dispose();
            }

            if (File.Exists(pidFile))
            {
                File.Delete(pidFile);
            }
        }
    }
    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Git Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }
}
