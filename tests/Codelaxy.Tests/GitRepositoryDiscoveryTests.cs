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

            Assert.True(
                expectedTopLevel.Succeeded,
                expectedTopLevel.StandardError);

            Assert.True(
                expectedGitDirectory.Succeeded,
                expectedGitDirectory.StandardError);

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
            DeleteDirectory(repositoryPath);
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
            DeleteDirectory(directoryPath);
        }
    }

    [Fact]
    public async Task TryDiscoverAsync_DistinguishesGitDirectoryFromCommonDirectoryInLinkedWorktree()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();
        var linkedWorktreePath = CreateTemporaryDirectory();

        try
        {
            Directory.Delete(linkedWorktreePath);

            var initResult = await runner.RunAsync(
                repositoryPath,
                ["init", "-b", "main"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "README.md"),
                "# test");

            var addResult = await runner.RunAsync(
                repositoryPath,
                ["add", "README.md"]);

            Assert.True(
                addResult.Succeeded,
                addResult.StandardError);

            var commitResult = await runner.RunAsync(
                repositoryPath,
                [
                    "-c", "user.name=Codelaxy Tests",
                    "-c", "user.email=codelaxy@example.invalid",
                    "commit",
                    "-m",
                    "initial"
                ]);

            Assert.True(
                commitResult.Succeeded,
                commitResult.StandardError);

            var worktreeResult = await runner.RunAsync(
                repositoryPath,
                [
                    "worktree",
                    "add",
                    "-b",
                    "linked-test",
                    linkedWorktreePath,
                    "HEAD"
                ]);

            Assert.True(
                worktreeResult.Succeeded,
                worktreeResult.StandardError);

            var expectedCommonDirectory = await runner.RunAsync(
                linkedWorktreePath,
                [
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir"
                ]);

            Assert.True(
                expectedCommonDirectory.Succeeded,
                expectedCommonDirectory.StandardError);

            var discovery =
                new GitRepositoryDiscovery(runner);

            var repository =
                await discovery.TryDiscoverAsync(linkedWorktreePath);

            Assert.NotNull(repository);

            Assert.Equal(
                expectedCommonDirectory.StandardOutput.Trim(),
                repository.GitCommonDirectory);

            Assert.NotEqual(
                repository.GitDirectory,
                repository.GitCommonDirectory);
        }
        finally
        {
            if (Directory.Exists(linkedWorktreePath))
            {
                var removeResult = await runner.RunAsync(
                    repositoryPath,
                    [
                        "worktree",
                        "remove",
                        "--force",
                        linkedWorktreePath
                    ]);

                if (!removeResult.Succeeded)
                {
                    DeleteDirectory(linkedWorktreePath);
                }
            }

            DeleteDirectory(repositoryPath);
        }
    }
    [Fact]
    public async Task DiscoverAsync_ReportsNotRepositoryOutsideRepository()
    {
        var runner = new GitProcessRunner();
        var directoryPath = CreateTemporaryDirectory();

        try
        {
            var discovery =
                new GitRepositoryDiscovery(runner);

            var result =
                await discovery.DiscoverAsync(directoryPath);

            Assert.False(result.Succeeded);
            Assert.Null(result.Repository);

            Assert.Equal(
                GitRepositoryDiscoveryFailureKind.NotRepository,
                result.FailureKind);

            Assert.False(
                string.IsNullOrWhiteSpace(result.Diagnostic));
        }
        finally
        {
            DeleteDirectory(directoryPath);
        }
    }

    [Fact]
    public async Task DiscoverAsync_ReportsBareRepository()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(
                repositoryPath,
                ["init", "--bare"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            var discovery =
                new GitRepositoryDiscovery(runner);

            var result =
                await discovery.DiscoverAsync(repositoryPath);

            Assert.False(result.Succeeded);
            Assert.Null(result.Repository);

            Assert.Equal(
                GitRepositoryDiscoveryFailureKind.BareRepository,
                result.FailureKind);

            Assert.False(
                string.IsNullOrWhiteSpace(result.Diagnostic));
        }
        finally
        {
            DeleteDirectory(repositoryPath);
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

    [Fact]
    public async Task DiscoverAsync_ReportsLaunchFailureWhenGitCannotBeStarted()
    {
        var runner = new GitProcessRunner(
            "codelaxy-git-executable-that-does-not-exist");

        var directoryPath = CreateTemporaryDirectory();

        try
        {
            var discovery =
                new GitRepositoryDiscovery(runner);

            var result =
                await discovery.DiscoverAsync(directoryPath);

            Assert.False(result.Succeeded);
            Assert.Null(result.Repository);

            Assert.Equal(
                GitRepositoryDiscoveryFailureKind.LaunchFailure,
                result.FailureKind);

            Assert.False(
                string.IsNullOrWhiteSpace(result.Diagnostic));
        }
        finally
        {
            DeleteDirectory(directoryPath);
        }
    }

    private static void DeleteDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(
                     path,
                     "*",
                     SearchOption.AllDirectories))
        {
            File.SetAttributes(file, FileAttributes.Normal);
        }

        foreach (var directory in Directory.EnumerateDirectories(
                     path,
                     "*",
                     SearchOption.AllDirectories))
        {
            File.SetAttributes(directory, FileAttributes.Normal);
        }

        File.SetAttributes(path, FileAttributes.Normal);

        Directory.Delete(path, recursive: true);
    }
}
