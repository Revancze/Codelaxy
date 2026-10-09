using Codelaxy.Contracts;
using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitSnapshotBuilderTests
{
    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeIdentityWhenUntrackedExecutableBitChangesOnLinux()
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

            var trackedPath = Path.Combine(repositoryPath, "README.md");

            await File.WriteAllTextAsync(trackedPath, "# test\n");
            await RunGitAsync(runner, repositoryPath, "add", "README.md");

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

            var scriptPath = Path.Combine(repositoryPath, "script.sh");

            await File.WriteAllTextAsync(scriptPath, "#!/bin/sh\necho hello\n");

            var builder = new GitSnapshotBuilder(runner);

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

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);

            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);

            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenUntrackedPathChanges()
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

            var firstPath = Path.Combine(repositoryPath, "first.txt");
            var secondPath = Path.Combine(repositoryPath, "second.txt");

            await File.WriteAllTextAsync(firstPath, "same content\n");

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Move(firstPath, secondPath);

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);
            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);
            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

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
    public async Task BuildAsync_ChangesOnlyWorkingTreeFingerprintWhenTrackedFileIsReplacedByDirectory()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "entry");

            await File.WriteAllTextAsync(trackedPath, "tracked file\n");

            await RunGitAsync(runner, repositoryPath, "add", "entry");

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

            Directory.CreateDirectory(trackedPath);

            await File.WriteAllTextAsync(
                Path.Combine(trackedPath, "child.txt"),
                "replacement directory\n"
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
    public async Task BuildAsync_ObservesDeletedTrackedFileMarkedAssumeUnchanged()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "content\n");

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

            await RunGitAsync(
                runner,
                repositoryPath,
                "update-index",
                "--assume-unchanged",
                "tracked.txt"
            );

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
    public async Task BuildAsync_ObservesExecutableBitChangeOnAssumeUnchangedTrackedFileOnLinux()
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

            var trackedPath = Path.Combine(repositoryPath, "script.sh");

            await File.WriteAllTextAsync(trackedPath, "#!/bin/sh\necho hello\n");

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

            await RunGitAsync(
                runner,
                repositoryPath,
                "update-index",
                "--assume-unchanged",
                "script.sh"
            );

            var assumeUnchangedResult = await runner.RunAsync(
                repositoryPath,
                ["ls-files", "-v", "--", "script.sh"]
            );

            Assert.True(assumeUnchangedResult.Succeeded, assumeUnchangedResult.StandardError);
            Assert.StartsWith("h ", assumeUnchangedResult.StandardOutput);

            var mode = File.GetUnixFileMode(trackedPath);

            File.SetUnixFileMode(
                trackedPath,
                mode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
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
    public async Task BuildAsync_ObservesDirectoryReplacingAssumeUnchangedTrackedFile()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "entry");

            await File.WriteAllTextAsync(trackedPath, "tracked file\n");

            await RunGitAsync(runner, repositoryPath, "add", "entry");

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

            await RunGitAsync(
                runner,
                repositoryPath,
                "update-index",
                "--assume-unchanged",
                "entry"
            );

            var assumeUnchangedResult = await runner.RunAsync(
                repositoryPath,
                ["ls-files", "-v", "--", "entry"]
            );

            Assert.True(assumeUnchangedResult.Succeeded, assumeUnchangedResult.StandardError);
            Assert.StartsWith("h ", assumeUnchangedResult.StandardOutput);

            File.Delete(trackedPath);

            Directory.CreateDirectory(trackedPath);

            await File.WriteAllTextAsync(
                Path.Combine(trackedPath, "child.txt"),
                "replacement directory\n"
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
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenUntrackedRegularFileBecomesSymlinkWithSameBlobIdentityOnLinux()
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

            var targetPath = Path.Combine(repositoryPath, "target");
            var entryPath = Path.Combine(repositoryPath, "entry");

            await File.WriteAllTextAsync(targetPath, "committed\n");

            await RunGitAsync(runner, repositoryPath, "add", "target");

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

            await File.WriteAllTextAsync(entryPath, "target");

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Delete(entryPath);

            File.CreateSymbolicLink(entryPath, "target");

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
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenTrackedSymlinkTargetChangesToSameContentOnLinux()
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

            var firstTargetPath = Path.Combine(repositoryPath, "first.txt");
            var secondTargetPath = Path.Combine(repositoryPath, "second.txt");
            var symlinkPath = Path.Combine(repositoryPath, "link.txt");

            await File.WriteAllTextAsync(firstTargetPath, "same-content\n");
            await File.WriteAllTextAsync(secondTargetPath, "same-content\n");

            File.CreateSymbolicLink(symlinkPath, "first.txt");

            await RunGitAsync(runner, repositoryPath, "add", "first.txt", "second.txt", "link.txt");

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

            File.Delete(symlinkPath);
            File.CreateSymbolicLink(symlinkPath, "second.txt");

            var statusResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--short"],
                GitCommandTimeout
            );

            Assert.True(statusResult.Succeeded, statusResult.StandardError);
            Assert.Contains("link.txt", statusResult.StandardOutput, StringComparison.Ordinal);

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
    public async Task BuildAsync_SupportsDanglingTrackedSymlinkOnLinux()
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

            var symlinkPath = Path.Combine(repositoryPath, "link.txt");

            File.CreateSymbolicLink(symlinkPath, "missing-target.txt");

            await RunGitAsync(runner, repositoryPath, "add", "link.txt");

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
                candidate => candidate.Path == "link.txt"
            );

            Assert.Equal("120000", entry.Mode);

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
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenUntrackedSymlinkTargetChangesToSameContentOnLinux()
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

            var firstTargetPath = Path.Combine(repositoryPath, "first.txt");
            var secondTargetPath = Path.Combine(repositoryPath, "second.txt");
            var symlinkPath = Path.Combine(repositoryPath, "link.txt");

            await File.WriteAllTextAsync(firstTargetPath, "same-content\n");
            await File.WriteAllTextAsync(secondTargetPath, "same-content\n");

            await RunGitAsync(runner, repositoryPath, "add", "first.txt", "second.txt");

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

            File.CreateSymbolicLink(symlinkPath, "first.txt");

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Delete(symlinkPath);
            File.CreateSymbolicLink(symlinkPath, "second.txt");

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
    public async Task BuildAsync_SupportsDanglingUntrackedSymlinkOnLinux()
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

            File.CreateSymbolicLink(Path.Combine(repositoryPath, "link.txt"), "missing-target.txt");

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
    public async Task BuildAsync_SupportsTrackedSymlinkToDirectoryOnLinux()
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

            var targetDirectory = Path.Combine(repositoryPath, "target");
            var symlinkPath = Path.Combine(repositoryPath, "link");

            Directory.CreateDirectory(targetDirectory);

            await File.WriteAllTextAsync(Path.Combine(targetDirectory, "file.txt"), "content\n");

            Directory.CreateSymbolicLink(symlinkPath, "target");

            await RunGitAsync(runner, repositoryPath, "add", "target/file.txt", "link");

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

            var linkEntry = Assert.Single(
                GitIndexEntryParser.Parse(indexResult.StandardOutput),
                candidate => candidate.Path == "link"
            );

            Assert.Equal("120000", linkEntry.Mode);

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
    public async Task BuildAsync_SupportsUntrackedSymlinkToDirectoryOnLinux()
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

            var targetDirectory = Path.Combine(repositoryPath, "target");
            var symlinkPath = Path.Combine(repositoryPath, "link");

            Directory.CreateDirectory(targetDirectory);

            await File.WriteAllTextAsync(Path.Combine(targetDirectory, "file.txt"), "content\n");

            await RunGitAsync(runner, repositoryPath, "add", "target/file.txt");

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

            Directory.CreateSymbolicLink(symlinkPath, "target");

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
    public async Task BuildAsync_DoesNotDependOnExternalTargetContentForTrackedSymlinkOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();
        var externalDirectory = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var externalTargetPath = Path.Combine(externalDirectory, "outside.txt");
            var symlinkPath = Path.Combine(repositoryPath, "link.txt");

            await File.WriteAllTextAsync(externalTargetPath, "outside-one\n");

            File.CreateSymbolicLink(symlinkPath, externalTargetPath);

            await RunGitAsync(runner, repositoryPath, "add", "link.txt");

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

            await File.WriteAllTextAsync(externalTargetPath, "outside-two\n");

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);
            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);
            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);
            Assert.Equal(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
            DeleteDirectory(externalDirectory);
        }
    }

    [Fact]
    public async Task BuildAsync_DoesNotDependOnExternalTargetContentForUntrackedSymlinkOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();
        var externalDirectory = CreateTemporaryDirectory();

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

            var externalTargetPath = Path.Combine(externalDirectory, "outside.txt");
            var symlinkPath = Path.Combine(repositoryPath, "link.txt");

            await File.WriteAllTextAsync(externalTargetPath, "outside-one\n");

            File.CreateSymbolicLink(symlinkPath, externalTargetPath);

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            await File.WriteAllTextAsync(externalTargetPath, "outside-two\n");

            var afterResult = await builder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);
            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);
            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);
            Assert.Equal(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
            DeleteDirectory(externalDirectory);
        }
    }

    [Fact]
    public async Task BuildAsync_SupportsNativeTrackedFileSymlinkOnWindows()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");
            await RunGitAsync(runner, repositoryPath, "config", "core.symlinks", "true");

            var targetPath = Path.Combine(repositoryPath, "target.txt");
            var linkPath = Path.Combine(repositoryPath, "link.txt");

            await File.WriteAllTextAsync(targetPath, "target\n");

            File.CreateSymbolicLink(linkPath, "target.txt");

            Assert.Equal("target.txt", new FileInfo(linkPath).LinkTarget);

            await RunGitAsync(runner, repositoryPath, "add", "target.txt", "link.txt");

            var indexResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["ls-files", "--stage", "-z"],
                GitCommandTimeout
            );

            Assert.True(indexResult.Succeeded, indexResult.StandardError);

            var linkEntry = Assert.Single(
                GitIndexEntryParser.Parse(indexResult.StandardOutput),
                entry => entry.Path == "link.txt"
            );

            Assert.Equal("120000", linkEntry.Mode);

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "add native symlink"
            );

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
    public async Task BuildAsync_SupportsTrackedSymlinkMaterializedAsRegularFileWhenCoreSymlinksFalse()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var payloadPath = Path.Combine(repositoryPath, "symlink-payload");

            await File.WriteAllTextAsync(payloadPath, "target.txt");

            var hashResult = await runner.RunAsync(
                repositoryPath,
                ["hash-object", "-w", "--", "symlink-payload"]
            );

            Assert.True(hashResult.Succeeded, hashResult.StandardError);

            var objectId = hashResult.StandardOutput.Trim();

            File.Delete(payloadPath);

            await RunGitAsync(
                runner,
                repositoryPath,
                "update-index",
                "--add",
                "--cacheinfo",
                $"120000,{objectId},link.txt"
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
                "add symlink"
            );

            await RunGitAsync(runner, repositoryPath, "config", "core.symlinks", "false");

            await RunGitAsync(runner, repositoryPath, "checkout", "--", "link.txt");

            var linkPath = Path.Combine(repositoryPath, "link.txt");

            Assert.Null(new FileInfo(linkPath).LinkTarget);
            Assert.Equal("target.txt", await File.ReadAllTextAsync(linkPath));

            var builder = new GitSnapshotBuilder(runner);

            var firstResult = await builder.BuildAsync(repositoryPath);

            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var firstSnapshot = Assert.IsType<Snapshot>(firstResult.Snapshot);

            await File.WriteAllTextAsync(linkPath, "other.txt");

            var secondResult = await builder.BuildAsync(repositoryPath);

            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var secondSnapshot = Assert.IsType<Snapshot>(secondResult.Snapshot);

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
    public async Task BuildAsync_ChangesWorkingTreeFingerprintWhenTrackedSymlinkBecomesRegularFileWithSameBlobIdentityOnLinux()
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

            var payloadPath = Path.Combine(repositoryPath, "symlink-payload");

            await File.WriteAllTextAsync(payloadPath, "target.txt");

            var hashResult = await runner.RunAsync(
                repositoryPath,
                ["hash-object", "-w", "--", "symlink-payload"]
            );

            Assert.True(hashResult.Succeeded, hashResult.StandardError);

            var objectId = hashResult.StandardOutput.Trim();

            File.Delete(payloadPath);

            await RunGitAsync(
                runner,
                repositoryPath,
                "update-index",
                "--add",
                "--cacheinfo",
                $"120000,{objectId},link.txt"
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
                "add symlink"
            );

            await RunGitAsync(runner, repositoryPath, "config", "core.symlinks", "true");

            await RunGitAsync(runner, repositoryPath, "checkout", "--", "link.txt");

            var linkPath = Path.Combine(repositoryPath, "link.txt");

            Assert.Equal("target.txt", new FileInfo(linkPath).LinkTarget);

            var builder = new GitSnapshotBuilder(runner);

            var beforeResult = await builder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            File.Delete(linkPath);

            await File.WriteAllTextAsync(linkPath, "target.txt");

            Assert.Null(new FileInfo(linkPath).LinkTarget);
            Assert.Equal("target.txt", await File.ReadAllTextAsync(linkPath));

            var statusResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["status", "--short"],
                GitCommandTimeout
            );

            Assert.True(statusResult.Succeeded, statusResult.StandardError);

            Assert.Contains(" T link.txt", statusResult.StandardOutput, StringComparison.Ordinal);

            var regularHashResult = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["hash-object", "--no-filters", "--", "link.txt"],
                GitCommandTimeout
            );

            Assert.True(regularHashResult.Succeeded, regularHashResult.StandardError);

            Assert.Equal(objectId, regularHashResult.StandardOutput.Trim());

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
    public async Task BuildAsync_UsesSameWorkingTreeFingerprintForMaterializedAndNativeTrackedSymlinkOnLinux()
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

            var payloadPath = Path.Combine(repositoryPath, "symlink-payload");

            await File.WriteAllTextAsync(payloadPath, "target.txt");

            var hashResult = await runner.RunAsync(
                repositoryPath,
                ["hash-object", "-w", "--", "symlink-payload"]
            );

            Assert.True(hashResult.Succeeded, hashResult.StandardError);

            var objectId = hashResult.StandardOutput.Trim();

            File.Delete(payloadPath);

            await RunGitAsync(
                runner,
                repositoryPath,
                "update-index",
                "--add",
                "--cacheinfo",
                $"120000,{objectId},link.txt"
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
                "add symlink"
            );

            await RunGitAsync(runner, repositoryPath, "config", "core.symlinks", "false");

            await RunGitAsync(runner, repositoryPath, "checkout", "--", "link.txt");

            var linkPath = Path.Combine(repositoryPath, "link.txt");

            var builder = new GitSnapshotBuilder(runner);

            // A: materializovaný symlink
            Assert.Null(new FileInfo(linkPath).LinkTarget);

            var materializedResult = await builder.BuildAsync(repositoryPath);
            Assert.True(materializedResult.Succeeded, materializedResult.Diagnostic);

            var materializedSnapshot = Assert.IsType<Snapshot>(materializedResult.Snapshot);

            // Donutit Git vytvořit skutečný symlink.
            File.Delete(linkPath);

            await RunGitAsync(runner, repositoryPath, "config", "core.symlinks", "true");

            await RunGitAsync(runner, repositoryPath, "checkout", "--", "link.txt");

            // Tohle je zásadní guard proti falešnému GREEN.
            Assert.Equal("target.txt", new FileInfo(linkPath).LinkTarget);

            var nativeResult = await builder.BuildAsync(repositoryPath);
            Assert.True(nativeResult.Succeeded, nativeResult.Diagnostic);

            var nativeSnapshot = Assert.IsType<Snapshot>(nativeResult.Snapshot);

            Assert.Equal(materializedSnapshot.HeadFingerprint, nativeSnapshot.HeadFingerprint);
            Assert.Equal(materializedSnapshot.IndexFingerprint, nativeSnapshot.IndexFingerprint);
            Assert.Equal(materializedSnapshot.StagedFingerprint, nativeSnapshot.StagedFingerprint);
            Assert.Equal(
                materializedSnapshot.WorkingTreeFingerprint,
                nativeSnapshot.WorkingTreeFingerprint
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

    [Fact]
    public async Task BuildAsync_DoesNotReturnMixedWorkingTreeObservationOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var setupRunner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();
        var wrapperDirectory = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(setupRunner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");
            var untrackedPath = Path.Combine(repositoryPath, "untracked.txt");

            await File.WriteAllTextAsync(trackedPath, "tracked-before\n");
            await RunGitAsync(setupRunner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                setupRunner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            await File.WriteAllTextAsync(untrackedPath, "untracked-before\n");

            var stableBuilder = new GitSnapshotBuilder(setupRunner);

            var beforeResult = await stableBuilder.BuildAsync(repositoryPath);

            Assert.True(beforeResult.Succeeded, beforeResult.Diagnostic);

            var beforeSnapshot = Assert.IsType<Snapshot>(beforeResult.Snapshot);

            var wrapperPath = Path.Combine(wrapperDirectory, "git-working-tree-mix-wrapper.sh");

            var markerPath = wrapperPath + ".mutated";

            await File.WriteAllTextAsync(
                wrapperPath,
                """
                #!/bin/sh

                marker="${0}.mutated"

                if [ "$#" -ge 6 ] \
                    && [ "$1" = "-C" ] \
                    && [ "$3" = "ls-files" ] \
                    && [ "$4" = "--others" ] \
                    && [ "$5" = "--exclude-per-directory=.gitignore" ] \
                    && [ "$6" = "-z" ] \
                    && [ ! -e "$marker" ]; then

                    printf 'tracked-after\n' > "$2/tracked.txt" || exit 97
                    printf 'untracked-after\n' > "$2/untracked.txt" || exit 98
                    : > "$marker" || exit 99
                fi

                exec git "$@"
                """
            );

            var wrapperMode = File.GetUnixFileMode(wrapperPath);

            File.SetUnixFileMode(
                wrapperPath,
                wrapperMode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            var raceRunner = new GitProcessRunner(wrapperPath);
            var builder = new GitSnapshotBuilder(raceRunner);

            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(
                File.Exists(markerPath),
                "The test Git wrapper did not mutate the working tree."
            );

            Assert.Equal("tracked-after\n", await File.ReadAllTextAsync(trackedPath));
            Assert.Equal("untracked-after\n", await File.ReadAllTextAsync(untrackedPath));

            var afterResult = await stableBuilder.BuildAsync(repositoryPath);

            Assert.True(afterResult.Succeeded, afterResult.Diagnostic);

            var afterSnapshot = Assert.IsType<Snapshot>(afterResult.Snapshot);

            Assert.Equal(beforeSnapshot.HeadFingerprint, afterSnapshot.HeadFingerprint);
            Assert.Equal(beforeSnapshot.IndexFingerprint, afterSnapshot.IndexFingerprint);
            Assert.Equal(beforeSnapshot.StagedFingerprint, afterSnapshot.StagedFingerprint);

            Assert.NotEqual(
                beforeSnapshot.WorkingTreeFingerprint,
                afterSnapshot.WorkingTreeFingerprint
            );

            if (!result.Succeeded)
            {
                Assert.Null(result.Snapshot);

                Assert.Contains(
                    "changed during snapshot capture",
                    result.Diagnostic,
                    StringComparison.OrdinalIgnoreCase
                );

                return;
            }

            var capturedSnapshot = Assert.IsType<Snapshot>(result.Snapshot);

            Assert.True(
                string.Equals(
                    capturedSnapshot.WorkingTreeFingerprint,
                    beforeSnapshot.WorkingTreeFingerprint,
                    StringComparison.Ordinal
                )
                    || string.Equals(
                        capturedSnapshot.WorkingTreeFingerprint,
                        afterSnapshot.WorkingTreeFingerprint,
                        StringComparison.Ordinal
                    ),
                "BuildAsync returned a mixed working-tree fingerprint "
                    + "that matches neither the state before nor the state after the mutation."
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
            DeleteDirectory(wrapperDirectory);
        }
    }

    [Fact]
    public async Task BuildAsync_FailsWhenRepositoryChangesDuringCaptureOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var setupRunner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();
        var wrapperDirectory = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(setupRunner, repositoryPath, "init", "-b", "main");

            var trackedPath = Path.Combine(repositoryPath, "tracked.txt");

            await File.WriteAllTextAsync(trackedPath, "main\n");

            await RunGitAsync(setupRunner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                setupRunner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "main state"
            );

            await RunGitAsync(setupRunner, repositoryPath, "switch", "-c", "race-target");

            await File.WriteAllTextAsync(trackedPath, "race target\n");

            await RunGitAsync(setupRunner, repositoryPath, "add", "tracked.txt");

            await RunGitAsync(
                setupRunner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "race target state"
            );

            await RunGitAsync(setupRunner, repositoryPath, "switch", "main");

            var wrapperPath = Path.Combine(wrapperDirectory, "git-race-wrapper.sh");
            var markerPath = wrapperPath + ".mutated";

            await File.WriteAllTextAsync(
                wrapperPath,
                """
                #!/bin/sh

                marker="${0}.mutated"

                if [ "$#" -ge 5 ] \
                    && [ "$1" = "-C" ] \
                    && [ "$3" = "rev-parse" ] \
                    && [ "$4" = "--verify" ] \
                    && [ "$5" = "HEAD" ] \
                    && [ ! -e "$marker" ]; then
                    output="$(git "$@")"
                    status=$?

                    if [ "$status" -eq 0 ]; then
                        : > "$marker"
                        GIT_OPTIONAL_LOCKS=1 git -C "$2" switch --quiet race-target
                    fi

                    printf '%s\n' "$output"
                    exit "$status"
                fi

                exec git "$@"
                """
            );

            var wrapperMode = File.GetUnixFileMode(wrapperPath);

            File.SetUnixFileMode(
                wrapperPath,
                wrapperMode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            var raceRunner = new GitProcessRunner(wrapperPath);
            var builder = new GitSnapshotBuilder(raceRunner);

            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(
                File.Exists(markerPath),
                "The test Git wrapper did not trigger the repository mutation."
            );

            var branchResult = await setupRunner.RunReadOnlyAsync(
                repositoryPath,
                ["branch", "--show-current"],
                GitCommandTimeout
            );

            Assert.True(branchResult.Succeeded, branchResult.StandardError);
            Assert.Equal("race-target", branchResult.StandardOutput.Trim());

            Assert.False(result.Succeeded);
            Assert.Null(result.Snapshot);

            Assert.Contains(
                "changed during snapshot capture",
                result.Diagnostic,
                StringComparison.OrdinalIgnoreCase
            );
        }
        finally
        {
            DeleteDirectory(repositoryPath);
            DeleteDirectory(wrapperDirectory);
        }
    }

    [Fact]
    public async Task BuildAsync_DoesNotExecuteRepositoryConfiguredFsmonitorHookOnLinux()
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

            var hookDirectory = Path.Combine(repositoryPath, ".git", "hooks");
            Directory.CreateDirectory(hookDirectory);

            var hookPath = Path.Combine(hookDirectory, "fsmonitor-test");
            var markerPath = Path.Combine(repositoryPath, ".git", "fsmonitor-ran");

            await File.WriteAllTextAsync(
                hookPath,
                """
                #!/bin/sh
                : > .git/fsmonitor-ran
                printf 'codelaxy-token\0'
                """
            );

            var hookMode = File.GetUnixFileMode(hookPath);

            File.SetUnixFileMode(
                hookPath,
                hookMode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            await RunGitAsync(runner, repositoryPath, "config", "core.fsmonitorHookVersion", "2");

            await RunGitAsync(
                runner,
                repositoryPath,
                "config",
                "core.fsmonitor",
                ".git/hooks/fsmonitor-test"
            );

            await RunGitAsync(runner, repositoryPath, "update-index", "--fsmonitor");
            if (File.Exists(markerPath))
            {
                File.Delete(markerPath);
            }

            var proofResult = await runner.RunAsync(
                repositoryPath,
                ["status", "--short"],
                GitCommandTimeout
            );

            Assert.True(proofResult.Succeeded, proofResult.StandardError);

            Assert.True(
                File.Exists(markerPath),
                "The repository-configured fsmonitor hook was not exercised by the test setup."
            );

            File.Delete(markerPath);

            var builder = new GitSnapshotBuilder(runner);

            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(result.Succeeded, result.Diagnostic);

            Assert.False(
                File.Exists(markerPath),
                "Snapshot observation executed the repository-configured core.fsmonitor hook."
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
