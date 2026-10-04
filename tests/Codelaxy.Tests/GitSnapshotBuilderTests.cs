using Codelaxy.Contracts;
using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitSnapshotBuilderTests
{
    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenContentChanges()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "committed\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            await File.WriteAllTextAsync(trackedPath, "unstaged-one\n");

            var firstStatus = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
                GitCommandTimeout
            );

            Assert.True(firstStatus.Succeeded, firstStatus.StandardError);

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            await File.WriteAllTextAsync(trackedPath, "unstaged-two\n");

            var secondStatus = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
                GitCommandTimeout
            );

            Assert.True(secondStatus.Succeeded, secondStatus.StandardError);

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

            Assert.Equal(firstStatus.StandardOutput, secondStatus.StandardOutput);

            Assert.Equal(firstSnapshot.HeadFingerprint, secondSnapshot.HeadFingerprint);

            Assert.Equal(firstSnapshot.IndexFingerprint, secondSnapshot.IndexFingerprint);

            Assert.Equal(firstSnapshot.StagedFingerprint, secondSnapshot.StagedFingerprint);

            Assert.NotEqual(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint
            );
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
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "tracked.txt"),
                "committed\n"
            );

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var untrackedPath = Path.Combine(repositoryPath, "untracked.txt");

            await File.WriteAllTextAsync(untrackedPath, "untracked-one\n");

            var builder = new GitSnapshotBuilder(runner);

            var firstStatus = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
                GitCommandTimeout
            );

            Assert.True(firstStatus.Succeeded, firstStatus.StandardError);

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            await File.WriteAllTextAsync(untrackedPath, "untracked-two\n");

            var secondStatus = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
                GitCommandTimeout
            );

            Assert.True(secondStatus.Succeeded, secondStatus.StandardError);

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

            Assert.Equal(firstStatus.StandardOutput, secondStatus.StandardOutput);

            Assert.Equal(firstSnapshot.HeadFingerprint, secondSnapshot.HeadFingerprint);

            Assert.Equal(firstSnapshot.IndexFingerprint, secondSnapshot.IndexFingerprint);

            Assert.Equal(firstSnapshot.StagedFingerprint, secondSnapshot.StagedFingerprint);

            Assert.NotEqual(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint
            );
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
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "committed\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            await File.WriteAllTextAsync(trackedPath, "staged\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            var builder = new GitSnapshotBuilder(runner);

            // A — staged state
            var stagedResult = await builder.BuildAsync(repositoryPath);

            Assert.True(stagedResult.Succeeded, stagedResult.Diagnostic);

            var stagedSnapshot = Assert.IsType<Snapshot>(stagedResult.Snapshot);

            // B — same HEAD/index, different unstaged content
            await File.WriteAllTextAsync(trackedPath, "unstaged\n");

            var unstagedResult = await builder.BuildAsync(repositoryPath);

            Assert.True(unstagedResult.Succeeded, unstagedResult.Diagnostic);

            var unstagedSnapshot = Assert.IsType<Snapshot>(unstagedResult.Snapshot);

            Assert.Equal(stagedSnapshot.HeadFingerprint, unstagedSnapshot.HeadFingerprint);

            Assert.Equal(stagedSnapshot.IndexFingerprint, unstagedSnapshot.IndexFingerprint);

            Assert.Equal(stagedSnapshot.StagedFingerprint, unstagedSnapshot.StagedFingerprint);

            Assert.NotEqual(
                stagedSnapshot.WorkingTreeFingerprint,
                unstagedSnapshot.WorkingTreeFingerprint
            );

            // C — same HEAD/index/staged identity, plus untracked file
            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "untracked.txt"),
                "untracked\n"
            );

            var untrackedResult = await builder.BuildAsync(repositoryPath);

            Assert.True(untrackedResult.Succeeded, untrackedResult.Diagnostic);

            var untrackedSnapshot = Assert.IsType<Snapshot>(untrackedResult.Snapshot);

            Assert.Equal(unstagedSnapshot.HeadFingerprint, untrackedSnapshot.HeadFingerprint);

            Assert.Equal(unstagedSnapshot.IndexFingerprint, untrackedSnapshot.IndexFingerprint);

            Assert.Equal(unstagedSnapshot.StagedFingerprint, untrackedSnapshot.StagedFingerprint);

            Assert.NotEqual(
                unstagedSnapshot.WorkingTreeFingerprint,
                untrackedSnapshot.WorkingTreeFingerprint
            );
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
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "tracked.txt"),
                "committed\n"
            );

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "tracked.txt"), "unstaged\n");

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "untracked.txt"),
                "untracked\n"
            );

            var builder = new GitSnapshotBuilder(runner);

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

            Assert.Equal(firstSnapshot.SchemaVersion, secondSnapshot.SchemaVersion);

            Assert.Equal(firstSnapshot.HeadFingerprint, secondSnapshot.HeadFingerprint);

            Assert.Equal(firstSnapshot.IndexFingerprint, secondSnapshot.IndexFingerprint);

            Assert.Equal(firstSnapshot.StagedFingerprint, secondSnapshot.StagedFingerprint);

            Assert.Equal(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint
            );
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
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "committed\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            await File.WriteAllTextAsync(trackedPath, "staged-one\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            await File.WriteAllTextAsync(trackedPath, "staged-two\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

            Assert.Equal(firstSnapshot.HeadFingerprint, secondSnapshot.HeadFingerprint);

            Assert.NotEqual(firstSnapshot.IndexFingerprint, secondSnapshot.IndexFingerprint);

            Assert.NotEqual(firstSnapshot.StagedFingerprint, secondSnapshot.StagedFingerprint);
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
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "committed\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Delete(trackedPath);

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
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
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "committed\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Delete(trackedPath);

            await RunGitAsync(runner, repositoryPath, "add", "-u");

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.NotEqual(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.NotEqual(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);
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
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var oldPath = Path.Combine(repositoryPath, "old.txt");

            var newPath = Path.Combine(repositoryPath, "new.txt");

            await File.WriteAllTextAsync(oldPath, "same-content\n");

            await RunGitAsync(runner, repositoryPath, "add", "old.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Move(oldPath, newPath);

            await RunGitAsync(runner, repositoryPath, "add", "-A");

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.NotEqual(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.NotEqual(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_FingerprintsDoNotDependOnStatusRenameConfiguration()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var oldPath = Path.Combine(repositoryPath, "old.txt");

            var newPath = Path.Combine(repositoryPath, "new.txt");

            await File.WriteAllTextAsync(oldPath, "same-content\n");

            await RunGitAsync(runner, repositoryPath, "add", "old.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            File.Move(oldPath, newPath);

            await RunGitAsync(runner, repositoryPath, "add", "-A");

            var builder = new GitSnapshotBuilder(runner);

            await RunGitAsync(runner, repositoryPath, "config", "status.renames", "true");

            var renameEnabledStatus = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
                GitCommandTimeout
            );

            Assert.True(renameEnabledStatus.Succeeded, renameEnabledStatus.StandardError);

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            await RunGitAsync(runner, repositoryPath, "config", "status.renames", "false");

            var renameDisabledStatus = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
                GitCommandTimeout
            );

            Assert.True(renameDisabledStatus.Succeeded, renameDisabledStatus.StandardError);

            Assert.NotEqual(
                renameEnabledStatus.StandardOutput,
                renameDisabledStatus.StandardOutput
            );

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

            Assert.Equal(firstSnapshot.HeadFingerprint, secondSnapshot.HeadFingerprint);

            Assert.Equal(firstSnapshot.IndexFingerprint, secondSnapshot.IndexFingerprint);

            Assert.Equal(firstSnapshot.StagedFingerprint, secondSnapshot.StagedFingerprint);

            Assert.Equal(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_FingerprintsDoNotDependOnCoreAutoCrlfConfiguration()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await RunGitAsync(runner, repositoryPath, "config", "core.autocrlf", "false");

            var filePath = Path.Combine(repositoryPath, "file.txt");

            await File.WriteAllTextAsync(filePath, "line-one\nline-two\n");

            await RunGitAsync(runner, repositoryPath, "add", "file.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            await File.WriteAllTextAsync(filePath, "line-one\r\nline-two\r\n");

            var builder = new GitSnapshotBuilder(runner);

            await RunGitAsync(runner, repositoryPath, "config", "core.autocrlf", "false");

            var autoCrlfDisabledDiff = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["diff", "--binary", "--no-ext-diff", "--no-textconv"],
                GitCommandTimeout
            );

            Assert.True(autoCrlfDisabledDiff.Succeeded, autoCrlfDisabledDiff.StandardError);

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            await RunGitAsync(runner, repositoryPath, "config", "core.autocrlf", "true");

            var autoCrlfEnabledDiff = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["diff", "--binary", "--no-ext-diff", "--no-textconv"],
                GitCommandTimeout
            );

            Assert.True(autoCrlfEnabledDiff.Succeeded, autoCrlfEnabledDiff.StandardError);

            Assert.NotEqual(
                autoCrlfDisabledDiff.StandardOutput,
                autoCrlfEnabledDiff.StandardOutput
            );

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

            Assert.Equal(firstSnapshot.HeadFingerprint, secondSnapshot.HeadFingerprint);

            Assert.Equal(firstSnapshot.IndexFingerprint, secondSnapshot.IndexFingerprint);

            Assert.Equal(firstSnapshot.StagedFingerprint, secondSnapshot.StagedFingerprint);

            Assert.Equal(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_DistinguishesDeletedAndEmptyTrackedFile()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "committed\n");

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            File.Delete(trackedPath);

            var deletedResult = await builder.BuildAsync(repositoryPath);

            Assert.True(deletedResult.Succeeded, deletedResult.Diagnostic);

            var deletedSnapshot = Assert.IsType<Snapshot>(deletedResult.Snapshot);

            await File.WriteAllTextAsync(trackedPath, string.Empty);

            var emptyResult = await builder.BuildAsync(repositoryPath);

            Assert.True(emptyResult.Succeeded, emptyResult.Diagnostic);

            var emptySnapshot = Assert.IsType<Snapshot>(emptyResult.Snapshot);

            Assert.Equal(deletedSnapshot.HeadFingerprint, emptySnapshot.HeadFingerprint);

            Assert.Equal(deletedSnapshot.IndexFingerprint, emptySnapshot.IndexFingerprint);

            Assert.Equal(deletedSnapshot.StagedFingerprint, emptySnapshot.StagedFingerprint);

            Assert.NotEqual(
                deletedSnapshot.WorkingTreeFingerprint,
                emptySnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_FingerprintsDoNotDependOnCoreExcludesFile()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        var ignoreFilePath = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Ignore {Guid.NewGuid():N}.txt"
        );

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "tracked.txt"),
                "committed\n"
            );

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "untracked.tmp"),
                "untracked\n"
            );

            await File.WriteAllTextAsync(ignoreFilePath, "*.tmp\n");

            var builder = new GitSnapshotBuilder(runner);

            var visibleResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--others", "--exclude-standard", "-z"],
                GitCommandTimeout
            );

            Assert.True(visibleResult.Succeeded, visibleResult.StandardError);

            Assert.Contains(
                "untracked.tmp",
                visibleResult.StandardOutput,
                StringComparison.Ordinal
            );

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            await RunGitAsync(
                runner,
                repositoryPath,
                "config",
                "core.excludesFile",
                ignoreFilePath
            );

            var ignoredResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--others", "--exclude-standard", "-z"],
                GitCommandTimeout
            );

            Assert.True(ignoredResult.Succeeded, ignoredResult.StandardError);

            Assert.DoesNotContain(
                "untracked.tmp",
                ignoredResult.StandardOutput,
                StringComparison.Ordinal
            );

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

            Assert.Equal(firstSnapshot.HeadFingerprint, secondSnapshot.HeadFingerprint);

            Assert.Equal(firstSnapshot.IndexFingerprint, secondSnapshot.IndexFingerprint);

            Assert.Equal(firstSnapshot.StagedFingerprint, secondSnapshot.StagedFingerprint);

            Assert.Equal(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);

            if (File.Exists(ignoreFilePath))
            {
                File.Delete(ignoreFilePath);
            }
        }
    }

    [Fact]
    public async Task BuildAsync_SupportsSha256Repository()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(
                runner,
                repositoryPath,
                "init",
                "--object-format=sha256",
                "-b",
                "main"
            );

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "tracked.txt"),
                "committed\n"
            );

            await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var objectFormat = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["rev-parse", "--show-object-format"],
                GitCommandTimeout
            );

            Assert.True(objectFormat.Succeeded, objectFormat.StandardError);

            Assert.Equal("sha256", objectFormat.StandardOutput.Trim());

            var head = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["rev-parse", "--verify", "HEAD"],
                GitCommandTimeout
            );

            Assert.True(head.Succeeded, head.StandardError);

            Assert.Equal(64, head.StandardOutput.Trim().Length);

            var builder = new GitSnapshotBuilder(runner);

            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(result.Succeeded, result.Diagnostic);

            Assert.IsType<Snapshot>(result.Snapshot);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_SupportsUnmergedRepositoryState()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var conflictPath = Path.Combine(repositoryPath, "conflict.txt");

            await File.WriteAllTextAsync(conflictPath, "base\n");

            await RunGitAsync(runner, repositoryPath, "add", "conflict.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "base"
            );

            await RunGitAsync(runner, repositoryPath, "switch", "-c", "theirs");

            await File.WriteAllTextAsync(conflictPath, "theirs\n");

            await RunGitAsync(runner, repositoryPath, "add", "conflict.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "theirs"
            );

            await RunGitAsync(runner, repositoryPath, "switch", "main");

            await File.WriteAllTextAsync(conflictPath, "ours\n");

            await RunGitAsync(runner, repositoryPath, "add", "conflict.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "ours"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            var mergeResult = await runner.RunAsync(
                repositoryPath,
                [
                    "-c",
                    "user.name=Codelaxy Tests",
                    "-c",
                    "user.email=codelaxy@example.invalid",
                    "merge",
                    "theirs",
                ]
            );

            Assert.False(mergeResult.Succeeded);

            var indexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(indexResult.Succeeded, indexResult.StandardError);

            var entries = GitIndexEntryParser.Parse(indexResult.StandardOutput);

            var conflictEntries = entries
                .Where(entry => entry.Path == "conflict.txt")
                .OrderBy(entry => entry.Stage)
                .ToArray();

            Assert.Equal([1, 2, 3], conflictEntries.Select(entry => entry.Stage));

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.NotEqual(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.NotEqual(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_RepresentsStagedCopyByHardState()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var sourcePath = Path.Combine(repositoryPath, "source.txt");

            var copyPath = Path.Combine(repositoryPath, "copy.txt");

            await File.WriteAllTextAsync(sourcePath, "same-content\n");

            await RunGitAsync(runner, repositoryPath, "add", "source.txt");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Copy(sourcePath, copyPath);

            await RunGitAsync(runner, repositoryPath, "add", "copy.txt");

            var indexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(indexResult.Succeeded, indexResult.StandardError);

            var entries = GitIndexEntryParser.Parse(indexResult.StandardOutput);

            var sourceEntry = Assert.Single(entries, entry => entry.Path == "source.txt");

            var copyEntry = Assert.Single(entries, entry => entry.Path == "copy.txt");

            Assert.Equal(0, sourceEntry.Stage);

            Assert.Equal(0, copyEntry.Stage);

            Assert.Equal(sourceEntry.ObjectId, copyEntry.ObjectId);

            Assert.NotEqual(sourceEntry.Path, copyEntry.Path);

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.NotEqual(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.NotEqual(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesStagedIdentityWhenExecutableBitChanges()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var scriptPath = Path.Combine(repositoryPath, "script.sh");

            await File.WriteAllTextAsync(scriptPath, "#!/bin/sh\necho hello\n");

            await RunGitAsync(runner, repositoryPath, "add", "script.sh");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeIndexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(beforeIndexResult.Succeeded, beforeIndexResult.StandardError);

            var beforeEntry = Assert.Single(
                GitIndexEntryParser.Parse(beforeIndexResult.StandardOutput),
                entry => entry.Path == "script.sh"
            );

            Assert.Equal("100644", beforeEntry.Mode);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            await RunGitAsync(runner, repositoryPath, "update-index", "--chmod=+x", "script.sh");

            var afterIndexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(afterIndexResult.Succeeded, afterIndexResult.StandardError);

            var afterEntry = Assert.Single(
                GitIndexEntryParser.Parse(afterIndexResult.StandardOutput),
                entry => entry.Path == "script.sh"
            );

            Assert.Equal("100755", afterEntry.Mode);

            Assert.Equal(beforeEntry.ObjectId, afterEntry.ObjectId);

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.NotEqual(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.NotEqual(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.Equal(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeIdentityWhenExecutableBitChangesOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var scriptPath = Path.Combine(repositoryPath, "script.sh");

            await File.WriteAllTextAsync(scriptPath, "#!/bin/sh\necho hello\n");

            await RunGitAsync(runner, repositoryPath, "add", "script.sh");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeIndexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(beforeIndexResult.Succeeded, beforeIndexResult.StandardError);

            var beforeEntry = Assert.Single(
                GitIndexEntryParser.Parse(beforeIndexResult.StandardOutput),
                entry => entry.Path == "script.sh"
            );

            Assert.Equal("100644", beforeEntry.Mode);

            var beforeHashResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["hash-object", "--no-filters", "script.sh"],
                GitCommandTimeout
            );

            Assert.True(beforeHashResult.Succeeded, beforeHashResult.StandardError);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            var mode = File.GetUnixFileMode(scriptPath);

            File.SetUnixFileMode(
                scriptPath,
                mode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            var afterIndexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(afterIndexResult.Succeeded, afterIndexResult.StandardError);

            var afterEntry = Assert.Single(
                GitIndexEntryParser.Parse(afterIndexResult.StandardOutput),
                entry => entry.Path == "script.sh"
            );

            Assert.Equal("100644", afterEntry.Mode);

            var statusResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--short"],
                GitCommandTimeout
            );

            Assert.True(statusResult.Succeeded, statusResult.StandardError);

            Assert.Contains(" M script.sh", statusResult.StandardOutput, StringComparison.Ordinal);

            var afterHashResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["hash-object", "--no-filters", "script.sh"],
                GitCommandTimeout
            );

            Assert.True(afterHashResult.Succeeded, afterHashResult.StandardError);

            Assert.Equal(
                beforeHashResult.StandardOutput.Trim(),
                afterHashResult.StandardOutput.Trim()
            );

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeIdentityWhenStagedExecutableBitMatchesWorkingTreeOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var scriptPath = Path.Combine(repositoryPath, "script.sh");

            await File.WriteAllTextAsync(scriptPath, "#!/bin/sh\necho hello\n");

            await RunGitAsync(runner, repositoryPath, "add", "script.sh");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            await RunGitAsync(runner, repositoryPath, "update-index", "--chmod=+x", "script.sh");

            var mode = File.GetUnixFileMode(scriptPath);

            File.SetUnixFileMode(
                scriptPath,
                mode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            var stagedIndexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(stagedIndexResult.Succeeded, stagedIndexResult.StandardError);

            var stagedEntry = Assert.Single(
                GitIndexEntryParser.Parse(stagedIndexResult.StandardOutput),
                candidate => candidate.Path == "script.sh"
            );

            Assert.Equal("100755", stagedEntry.Mode);

            var workingTreeMode = File.GetUnixFileMode(scriptPath);

            Assert.True((workingTreeMode & UnixFileMode.UserExecute) != 0);

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.NotEqual(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.NotEqual(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_FileModeConfigurationDoesNotChangeExecutableWorkingTreeIdentityOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var scriptPath = Path.Combine(repositoryPath, "script.sh");

            await File.WriteAllTextAsync(scriptPath, "#!/bin/sh\necho hello\n");

            await RunGitAsync(runner, repositoryPath, "add", "script.sh");
            await RunGitAsync(runner, repositoryPath, "update-index", "--chmod=+x", "script.sh");

            var mode = File.GetUnixFileMode(scriptPath);

            File.SetUnixFileMode(
                scriptPath,
                mode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            var indexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(indexResult.Succeeded, indexResult.StandardError);

            var entry = Assert.Single(
                GitIndexEntryParser.Parse(indexResult.StandardOutput),
                candidate => candidate.Path == "script.sh"
            );

            Assert.Equal("100755", entry.Mode);

            var builder = new GitSnapshotBuilder(runner);

            await RunGitAsync(runner, repositoryPath, "config", "core.fileMode", "true");

            var enabledResult = await builder.BuildAsync(repositoryPath);

            Assert.True(enabledResult.Succeeded, enabledResult.Diagnostic);

            var enabledSnapshot = Assert.IsType<Snapshot>(enabledResult.Snapshot);

            await RunGitAsync(runner, repositoryPath, "config", "core.fileMode", "false");

            var disabledResult = await builder.BuildAsync(repositoryPath);

            Assert.True(disabledResult.Succeeded, disabledResult.Diagnostic);

            var disabledSnapshot = Assert.IsType<Snapshot>(disabledResult.Snapshot);

            Assert.Equal(enabledSnapshot.HeadFingerprint, disabledSnapshot.HeadFingerprint);
            Assert.Equal(enabledSnapshot.IndexFingerprint, disabledSnapshot.IndexFingerprint);
            Assert.Equal(enabledSnapshot.StagedFingerprint, disabledSnapshot.StagedFingerprint);
            Assert.Equal(
                enabledSnapshot.WorkingTreeFingerprint,
                disabledSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeIdentityWhenExecutableBitChangesWithFileModeDisabledOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var scriptPath = Path.Combine(repositoryPath, "script.sh");

            await File.WriteAllTextAsync(scriptPath, "#!/bin/sh\necho hello\n");

            await RunGitAsync(runner, repositoryPath, "add", "script.sh");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            await RunGitAsync(runner, repositoryPath, "config", "core.fileMode", "false");

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            var beforeHashResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["hash-object", "--no-filters", "script.sh"],
                GitCommandTimeout
            );

            Assert.True(beforeHashResult.Succeeded, beforeHashResult.StandardError);

            var mode = File.GetUnixFileMode(scriptPath);

            File.SetUnixFileMode(
                scriptPath,
                mode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            var statusResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--short"],
                GitCommandTimeout
            );

            Assert.True(statusResult.Succeeded, statusResult.StandardError);
            Assert.Equal(string.Empty, statusResult.StandardOutput);

            var afterHashResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["hash-object", "--no-filters", "script.sh"],
                GitCommandTimeout
            );

            Assert.True(afterHashResult.Succeeded, afterHashResult.StandardError);

            Assert.Equal(
                beforeHashResult.StandardOutput.Trim(),
                afterHashResult.StandardOutput.Trim()
            );

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);
            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);
            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    private static async Task RunGitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments
    )
    {
        var result = await runner.RunAsync(repositoryPath, arguments);

        Assert.True(result.Succeeded, result.StandardError);
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), $"Codelaxy Snapshot Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }

    private static void DeleteDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
        {
            File.SetAttributes(file, FileAttributes.Normal);
        }

        foreach (
            var directory in Directory.EnumerateDirectories(path, "*", SearchOption.AllDirectories)
        )
        {
            File.SetAttributes(directory, FileAttributes.Normal);
        }

        File.SetAttributes(path, FileAttributes.Normal);

        Directory.Delete(path, recursive: true);
    }
}
