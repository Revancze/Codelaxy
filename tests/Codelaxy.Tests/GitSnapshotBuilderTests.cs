using Codelaxy.Contracts;
using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitSnapshotBuilderTests
{
    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenContentChanges()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "-b",
                "main");

            var trackedPath =
                Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(
                trackedPath,
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

            var builder =
                new GitSnapshotBuilder(runner);

            await File.WriteAllTextAsync(
                trackedPath,
                "unstaged-one\n");

            var firstStatus =
                await runner.RunReadOnlyAsync(
                    repositoryPath,
                    [
                        "status",
                    "--porcelain=v2",
                    "-z",
                    "--untracked-files=all"
                    ]);

            Assert.True(
                firstStatus.Succeeded,
                firstStatus.StandardError);

            var firstResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                firstResult.Succeeded,
                firstResult.Diagnostic);

            var firstSnapshot =
                Assert.IsType<Snapshot>(
                    firstResult.Snapshot);

            await File.WriteAllTextAsync(
                trackedPath,
                "unstaged-two\n");

            var secondStatus =
                await runner.RunReadOnlyAsync(
                    repositoryPath,
                    [
                        "status",
                    "--porcelain=v2",
                    "-z",
                    "--untracked-files=all"
                    ]);

            Assert.True(
                secondStatus.Succeeded,
                secondStatus.StandardError);

            var secondResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                secondResult.Succeeded,
                secondResult.Diagnostic);

            var secondSnapshot =
                Assert.IsType<Snapshot>(
                    secondResult.Snapshot);

            Assert.Equal(
                firstStatus.StandardOutput,
                secondStatus.StandardOutput);

            Assert.Equal(
                firstSnapshot.HeadFingerprint,
                secondSnapshot.HeadFingerprint);

            Assert.Equal(
                firstSnapshot.IndexFingerprint,
                secondSnapshot.IndexFingerprint);

            Assert.Equal(
                firstSnapshot.StagedFingerprint,
                secondSnapshot.StagedFingerprint);

            Assert.NotEqual(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenUntrackedContentChanges()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
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

            var untrackedPath =
                Path.Combine(
                    repositoryPath,
                    "untracked.txt");

            await File.WriteAllTextAsync(
                untrackedPath,
                "untracked-one\n");

            var builder =
                new GitSnapshotBuilder(runner);

            var firstStatus =
                await runner.RunReadOnlyAsync(
                    repositoryPath,
                    [
                        "status",
                        "--porcelain=v2",
                        "-z",
                        "--untracked-files=all"
                    ]);

            Assert.True(
                firstStatus.Succeeded,
                firstStatus.StandardError);

            var firstResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                firstResult.Succeeded,
                firstResult.Diagnostic);

            var firstSnapshot =
                Assert.IsType<Snapshot>(
                    firstResult.Snapshot);

            await File.WriteAllTextAsync(
                untrackedPath,
                "untracked-two\n");

            var secondStatus =
                await runner.RunReadOnlyAsync(
                    repositoryPath,
                    [
                        "status",
                        "--porcelain=v2",
                        "-z",
                        "--untracked-files=all"
                    ]);

            Assert.True(
                secondStatus.Succeeded,
                secondStatus.StandardError);

            var secondResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                secondResult.Succeeded,
                secondResult.Diagnostic);

            var secondSnapshot =
                Assert.IsType<Snapshot>(
                    secondResult.Snapshot);

            Assert.Equal(
                firstStatus.StandardOutput,
                secondStatus.StandardOutput);

            Assert.Equal(
                firstSnapshot.HeadFingerprint,
                secondSnapshot.HeadFingerprint);

            Assert.Equal(
                firstSnapshot.IndexFingerprint,
                secondSnapshot.IndexFingerprint);

            Assert.Equal(
                firstSnapshot.StagedFingerprint,
                secondSnapshot.StagedFingerprint);

            Assert.NotEqual(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_SeparatesStagedAndWorkingTreeIdentity()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "-b",
                "main");

            var trackedPath =
                Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(
                trackedPath,
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

            await File.WriteAllTextAsync(
                trackedPath,
                "staged\n");

            await RunGitAsync(
                runner,
                repositoryPath,
                "add",
                "tracked.txt");

            var builder =
                new GitSnapshotBuilder(runner);

            // A — staged state
            var stagedResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                stagedResult.Succeeded,
                stagedResult.Diagnostic);

            var stagedSnapshot =
                Assert.IsType<Snapshot>(
                    stagedResult.Snapshot);

            // B — same HEAD/index, different unstaged content
            await File.WriteAllTextAsync(
                trackedPath,
                "unstaged\n");

            var unstagedResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                unstagedResult.Succeeded,
                unstagedResult.Diagnostic);

            var unstagedSnapshot =
                Assert.IsType<Snapshot>(
                    unstagedResult.Snapshot);

            Assert.Equal(
                stagedSnapshot.HeadFingerprint,
                unstagedSnapshot.HeadFingerprint);

            Assert.Equal(
                stagedSnapshot.IndexFingerprint,
                unstagedSnapshot.IndexFingerprint);

            Assert.Equal(
                stagedSnapshot.StagedFingerprint,
                unstagedSnapshot.StagedFingerprint);

            Assert.NotEqual(
                stagedSnapshot.WorkingTreeFingerprint,
                unstagedSnapshot.WorkingTreeFingerprint);

            // C — same HEAD/index/staged identity, plus untracked file
            await File.WriteAllTextAsync(
                Path.Combine(
                    repositoryPath,
                    "untracked.txt"),
                "untracked\n");

            var untrackedResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                untrackedResult.Succeeded,
                untrackedResult.Diagnostic);

            var untrackedSnapshot =
                Assert.IsType<Snapshot>(
                    untrackedResult.Snapshot);

            Assert.Equal(
                unstagedSnapshot.HeadFingerprint,
                untrackedSnapshot.HeadFingerprint);

            Assert.Equal(
                unstagedSnapshot.IndexFingerprint,
                untrackedSnapshot.IndexFingerprint);

            Assert.Equal(
                unstagedSnapshot.StagedFingerprint,
                untrackedSnapshot.StagedFingerprint);

            Assert.NotEqual(
                unstagedSnapshot.WorkingTreeFingerprint,
                untrackedSnapshot.WorkingTreeFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ProducesSameFingerprintsForSameRepositoryState()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
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

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "tracked.txt"),
                "unstaged\n");

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "untracked.txt"),
                "untracked\n");

            var builder =
                new GitSnapshotBuilder(runner);

            var firstResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                firstResult.Succeeded,
                firstResult.Diagnostic);

            var firstSnapshot =
                Assert.IsType<Snapshot>(
                    firstResult.Snapshot);

            var secondResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                secondResult.Succeeded,
                secondResult.Diagnostic);

            var secondSnapshot =
                Assert.IsType<Snapshot>(
                    secondResult.Snapshot);

            Assert.Equal(
                firstSnapshot.SchemaVersion,
                secondSnapshot.SchemaVersion);

            Assert.Equal(
                firstSnapshot.HeadFingerprint,
                secondSnapshot.HeadFingerprint);

            Assert.Equal(
                firstSnapshot.IndexFingerprint,
                secondSnapshot.IndexFingerprint);

            Assert.Equal(
                firstSnapshot.StagedFingerprint,
                secondSnapshot.StagedFingerprint);

            Assert.Equal(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesIndexAndStagedFingerprintsWhenStagedContentChanges()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "-b",
                "main");

            var trackedPath =
                Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(
                trackedPath,
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

            var builder =
                new GitSnapshotBuilder(runner);

            await File.WriteAllTextAsync(
                trackedPath,
                "staged-one\n");

            await RunGitAsync(
                runner,
                repositoryPath,
                "add",
                "tracked.txt");

            var firstResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                firstResult.Succeeded,
                firstResult.Diagnostic);

            var firstSnapshot =
                Assert.IsType<Snapshot>(
                    firstResult.Snapshot);

            await File.WriteAllTextAsync(
                trackedPath,
                "staged-two\n");

            await RunGitAsync(
                runner,
                repositoryPath,
                "add",
                "tracked.txt");

            var secondResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                secondResult.Succeeded,
                secondResult.Diagnostic);

            var secondSnapshot =
                Assert.IsType<Snapshot>(
                    secondResult.Snapshot);

            Assert.Equal(
                firstSnapshot.HeadFingerprint,
                secondSnapshot.HeadFingerprint);

            Assert.NotEqual(
                firstSnapshot.IndexFingerprint,
                secondSnapshot.IndexFingerprint);

            Assert.NotEqual(
                firstSnapshot.StagedFingerprint,
                secondSnapshot.StagedFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesOnlyWorkingTreeFingerprintForUnstagedDeletion()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "-b",
                "main");

            var trackedPath =
                Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(
                trackedPath,
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

            var builder =
                new GitSnapshotBuilder(runner);

            var beforeResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                beforeResult.Succeeded,
                beforeResult.Diagnostic);

            var beforeSnapshot =
                Assert.IsType<Snapshot>(
                    beforeResult.Snapshot);

            File.Delete(trackedPath);

            var afterResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                afterResult.Succeeded,
                afterResult.Diagnostic);

            var afterSnapshot =
                Assert.IsType<Snapshot>(
                    afterResult.Snapshot);

            Assert.Equal(
                beforeSnapshot.HeadFingerprint,
                afterSnapshot.HeadFingerprint);

            Assert.Equal(
                beforeSnapshot.IndexFingerprint,
                afterSnapshot.IndexFingerprint);

            Assert.Equal(
                beforeSnapshot.StagedFingerprint,
                afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesIndexAndStagedFingerprintsForStagedDeletion()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "-b",
                "main");

            var trackedPath =
                Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(
                trackedPath,
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

            var builder =
                new GitSnapshotBuilder(runner);

            var beforeResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                beforeResult.Succeeded,
                beforeResult.Diagnostic);

            var beforeSnapshot =
                Assert.IsType<Snapshot>(
                    beforeResult.Snapshot);

            File.Delete(trackedPath);

            await RunGitAsync(
                runner,
                repositoryPath,
                "add",
                "-u");

            var afterResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                afterResult.Succeeded,
                afterResult.Diagnostic);

            var afterSnapshot =
                Assert.IsType<Snapshot>(
                    afterResult.Snapshot);

            Assert.Equal(
                beforeSnapshot.HeadFingerprint,
                afterSnapshot.HeadFingerprint);

            Assert.NotEqual(
                beforeSnapshot.IndexFingerprint,
                afterSnapshot.IndexFingerprint);

            Assert.NotEqual(
                beforeSnapshot.StagedFingerprint,
                afterSnapshot.StagedFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesIndexAndStagedFingerprintsForStagedRename()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "-b",
                "main");

            var oldPath =
                Path.Combine(repositoryPath, "old.txt");

            var newPath =
                Path.Combine(repositoryPath, "new.txt");

            await File.WriteAllTextAsync(
                oldPath,
                "same-content\n");

            await RunGitAsync(
                runner,
                repositoryPath,
                "add",
                "old.txt");

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

            var builder =
                new GitSnapshotBuilder(runner);

            var beforeResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                beforeResult.Succeeded,
                beforeResult.Diagnostic);

            var beforeSnapshot =
                Assert.IsType<Snapshot>(
                    beforeResult.Snapshot);

            File.Move(
                oldPath,
                newPath);

            await RunGitAsync(
                runner,
                repositoryPath,
                "add",
                "-A");

            var afterResult =
                await builder.BuildAsync(repositoryPath);

            Assert.True(
                afterResult.Succeeded,
                afterResult.Diagnostic);

            var afterSnapshot =
                Assert.IsType<Snapshot>(
                    afterResult.Snapshot);

            Assert.Equal(
                beforeSnapshot.HeadFingerprint,
                afterSnapshot.HeadFingerprint);

            Assert.NotEqual(
                beforeSnapshot.IndexFingerprint,
                afterSnapshot.IndexFingerprint);

            Assert.NotEqual(
                beforeSnapshot.StagedFingerprint,
                afterSnapshot.StagedFingerprint);
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
        var result = await runner.RunAsync(
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
            $"Codelaxy Snapshot Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
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