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
}
