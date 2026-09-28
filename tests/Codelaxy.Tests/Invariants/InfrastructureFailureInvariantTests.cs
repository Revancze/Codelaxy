using Codelaxy.Git;

namespace Codelaxy.Tests.Invariants;

public class InfrastructureFailureInvariantTests
{
    private static readonly TimeSpan GitCommandTimeout =
    TimeSpan.FromSeconds(30);
    [Fact]
    public async Task SnapshotBuild_ReturnsNoSnapshotWhenGitCannotStart()
    {
        var repositoryPath =
            CreateTemporaryDirectory();

        try
        {
            var runner = new GitProcessRunner(
                "codelaxy-git-executable-that-does-not-exist");

            var builder =
                new GitSnapshotBuilder(runner);

            var result =
                await builder.BuildAsync(repositoryPath);

            Assert.False(result.Succeeded);
            Assert.Null(result.Snapshot);

            Assert.False(
                string.IsNullOrWhiteSpace(
                    result.Diagnostic));
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task SnapshotBuild_ReturnsNoSnapshotOutsideRepository()
    {
        var repositoryPath =
            CreateTemporaryDirectory();

        try
        {
            var runner =
                new GitProcessRunner();

            var builder =
                new GitSnapshotBuilder(runner);

            var result =
                await builder.BuildAsync(repositoryPath);

            Assert.False(result.Succeeded);
            Assert.Null(result.Snapshot);

            Assert.False(
                string.IsNullOrWhiteSpace(
                    result.Diagnostic));
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task SnapshotBuild_ReturnsNoSnapshotForBareRepository()
    {
        var repositoryPath =
            CreateTemporaryDirectory();

        try
        {
            var runner =
                new GitProcessRunner();

            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "--bare");

            var builder =
                new GitSnapshotBuilder(runner);

            var result =
                await builder.BuildAsync(repositoryPath);

            Assert.False(result.Succeeded);
            Assert.Null(result.Snapshot);

            Assert.False(
                string.IsNullOrWhiteSpace(
                    result.Diagnostic));
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task SnapshotBuild_ReturnsNoSnapshotWhenObservationFailsAfterDiscovery()
    {
        var repositoryPath =
            CreateTemporaryDirectory();

        try
        {
            var runner =
                new GitProcessRunner();

            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "-b",
                "main");

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "tracked.txt"),
                "committed\n");

            await RunGitAsync(
                runner,
                repositoryPath,
                "add",
                "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial");

            var indexPath =
                Path.Combine(
                    repositoryPath,
                    ".git",
                    "index");

            await File.WriteAllTextAsync(
                indexPath,
                "this is not a git index\n");

            var discovery =
                new GitRepositoryDiscovery(runner);

            var discoveryResult =
                await discovery.DiscoverAsync(repositoryPath);

            Assert.True(
                discoveryResult.Succeeded,
                discoveryResult.Diagnostic);

            var headResult =
                await runner.RunReadOnlyAsync(
                    repositoryPath,
                    [
                        "rev-parse",
                    "--verify",
                    "HEAD"
                    ], GitCommandTimeout);

            Assert.True(
                headResult.Succeeded,
                headResult.StandardError);

            var indexResult =
                await runner.RunReadOnlyAsync(
                    repositoryPath,
                    [
                        "ls-files",
                    "--stage",
                    "-z"
                    ], GitCommandTimeout);

            Assert.False(
                indexResult.Succeeded);

            var builder =
                new GitSnapshotBuilder(runner);

            var result =
                await builder.BuildAsync(repositoryPath);

            Assert.False(result.Succeeded);
            Assert.Null(result.Snapshot);

            Assert.False(
                string.IsNullOrWhiteSpace(
                    result.Diagnostic));
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    private static async Task RunGitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments)
    {
        var result =
            await runner.RunAsync(
                repositoryPath,
                arguments);

        Assert.True(
            result.Succeeded,
            result.StandardError);
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Infrastructure Invariant Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }

    private static void DeleteDirectory(
        string path)
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
            File.SetAttributes(
                file,
                FileAttributes.Normal);
        }

        foreach (var directory in Directory.EnumerateDirectories(
                     path,
                     "*",
                     SearchOption.AllDirectories))
        {
            File.SetAttributes(
                directory,
                FileAttributes.Normal);
        }

        File.SetAttributes(
            path,
            FileAttributes.Normal);

        Directory.Delete(
            path,
            recursive: true);
    }
}
