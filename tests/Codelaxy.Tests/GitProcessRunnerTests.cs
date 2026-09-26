using Codelaxy.Git;

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

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Git Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }
}
