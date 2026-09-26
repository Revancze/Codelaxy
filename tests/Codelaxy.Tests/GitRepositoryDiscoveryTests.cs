using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitRepositoryDiscoveryTests
{
    [Fact]
    public async Task TryDiscoverAsync_FindsRepositoryFromNestedDirectory()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(
                repositoryPath,
                ["init"]);

            Assert.True(initResult.Succeeded, initResult.StandardError);

            var nestedPath = Path.Combine(
                repositoryPath,
                "nested",
                "directory with spaces");

            Directory.CreateDirectory(nestedPath);

            var expectedTopLevel = await runner.RunAsync(
                nestedPath,
                ["rev-parse", "--show-toplevel"]);

            var expectedGitDirectory = await runner.RunAsync(
                nestedPath,
                ["rev-parse", "--absolute-git-dir"]);

            Assert.True(expectedTopLevel.Succeeded);
            Assert.True(expectedGitDirectory.Succeeded);

            var discovery =
                new GitRepositoryDiscovery(runner);

            var repository =
                await discovery.TryDiscoverAsync(nestedPath);

            Assert.NotNull(repository);

            Assert.Equal(
                expectedTopLevel.StandardOutput.Trim(),
                repository.TopLevel);

            Assert.Equal(
                expectedGitDirectory.StandardOutput.Trim(),
                repository.GitDirectory);
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
        }
    }

    [Fact]
    public async Task TryDiscoverAsync_ReturnsNullOutsideRepository()
    {
        var runner = new GitProcessRunner();
        var directoryPath = CreateTemporaryDirectory();

        try
        {
            var discovery =
                new GitRepositoryDiscovery(runner);

            var repository =
                await discovery.TryDiscoverAsync(directoryPath);

            Assert.Null(repository);
        }
        finally
        {
            Directory.Delete(directoryPath, recursive: true);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Discovery Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }
}
