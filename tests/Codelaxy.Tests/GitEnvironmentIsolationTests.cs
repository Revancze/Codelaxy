using Codelaxy.Git;

namespace Codelaxy.Tests;

[CollectionDefinition("Git environment", DisableParallelization = true)]
public sealed class GitEnvironmentCollection;

[Collection("Git environment")]
public class GitEnvironmentIsolationTests
{
    [Fact]
    public async Task RunAsync_IgnoresInheritedGitDir()
    {
        await AssertVariableIsIgnoredAsync(
            "GIT_DIR",
            ["rev-parse", "--git-dir"]);
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitWorkTree()
    {
        await AssertVariableIsIgnoredAsync(
            "GIT_WORK_TREE",
            ["rev-parse", "--show-toplevel"]);
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitIndexFile()
    {
        await AssertVariableIsIgnoredAsync(
            "GIT_INDEX_FILE",
            ["rev-parse", "--git-path", "index"]);
    }

    private static async Task AssertVariableIsIgnoredAsync(
        string variableName,
        IEnumerable<string> arguments)
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();
        var originalValue =
            Environment.GetEnvironmentVariable(variableName);

        var poisonMarker =
            $"CODELAXY_POISON_{Guid.NewGuid():N}";

        var poisonPath =
            Path.Combine(repositoryPath, poisonMarker);

        try
        {
            var initResult = await runner.RunAsync(
                repositoryPath,
                ["init"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            Environment.SetEnvironmentVariable(
                variableName,
                poisonPath);

            var result = await runner.RunAsync(
                repositoryPath,
                arguments);

            Assert.True(
                result.Succeeded,
                result.StandardError);

            Assert.DoesNotContain(
                poisonMarker,
                result.StandardOutput,
                StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                variableName,
                originalValue);

            Directory.Delete(
                repositoryPath,
                recursive: true);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Git Env Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }
}
