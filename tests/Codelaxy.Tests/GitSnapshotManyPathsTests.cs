using Codelaxy.Git;

namespace Codelaxy.Tests;

public sealed class GitSnapshotManyPathsTests
{
    [WindowsOnlyFact]
    public async Task BuildAsync_HandlesTrackedPathsExceedingWindowsCommandLineLimit()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy F1 Tracked {Guid.NewGuid():N}"
        );

        Directory.CreateDirectory(repositoryPath);

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            const int fileCount = 450;
            var longPart = new string('a', 70);

            for (var index = 0; index < fileCount; index++)
            {
                var fileName =
                    $"file-{index.ToString("D4", System.Globalization.CultureInfo.InvariantCulture)}-{longPart}.txt";
                var filePath = Path.Combine(repositoryPath, fileName);

                await File.WriteAllTextAsync(
                    filePath,
                    $"content-{index.ToString(System.Globalization.CultureInfo.InvariantCulture)}\n"
                );
            }

            await RunGitAsync(runner, repositoryPath, "add", "-A");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "F1 tracked paths fixture"
            );

            var builder = new GitSnapshotBuilder(runner);
            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.NotNull(result.Snapshot);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [WindowsOnlyFact]
    public async Task BuildAsync_HandlesUntrackedPathsExceedingWindowsCommandLineLimit()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy F1 Untracked {Guid.NewGuid():N}"
        );

        Directory.CreateDirectory(repositoryPath);

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "tracked.txt"), "baseline\n");

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
                "F1 untracked paths fixture"
            );

            const int fileCount = 450;
            var longPart = new string('u', 70);

            for (var index = 0; index < fileCount; index++)
            {
                var fileName =
                    "untracked-"
                    + index.ToString("D4", System.Globalization.CultureInfo.InvariantCulture)
                    + "-"
                    + longPart
                    + ".txt";

                await File.WriteAllTextAsync(Path.Combine(repositoryPath, fileName), "payload\n");
            }

            var builder = new GitSnapshotBuilder(runner);

            var firstResult = await builder.BuildAsync(repositoryPath);
            Assert.True(firstResult.Succeeded, firstResult.Diagnostic);

            var first = Assert.IsType<Codelaxy.Contracts.Snapshot>(firstResult.Snapshot);

            await File.WriteAllTextAsync(
                Path.Combine(repositoryPath, "untracked-0000-" + longPart + ".txt"),
                "changed\n"
            );

            var secondResult = await builder.BuildAsync(repositoryPath);
            Assert.True(secondResult.Succeeded, secondResult.Diagnostic);

            var second = Assert.IsType<Codelaxy.Contracts.Snapshot>(secondResult.Snapshot);

            Assert.Equal(first.HeadFingerprint, second.HeadFingerprint);
            Assert.Equal(first.IndexFingerprint, second.IndexFingerprint);
            Assert.Equal(first.StagedFingerprint, second.StagedFingerprint);

            Assert.NotEqual(first.WorkingTreeFingerprint, second.WorkingTreeFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task BuildAsync_ObservesSpecialNamesWithoutLosingWorkingTreeChanges(bool tracked)
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "README.md"), "baseline\n");

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
                "F1 special paths fixture"
            );

            var names = new List<string>
            {
                "space name.txt",
                "-leading-dash.txt",
                "český-žluťoučký.txt",
                "日本語-文書.txt",
                "emoji-\U0001F600.txt",
                "composed-é.txt",
                "decomposed-e\u0301.txt",
            };

            if (!OperatingSystem.IsWindows())
            {
                names.Add("\"leading-quote.txt");
                names.Add("back\\slash.txt");
                names.Add("tab\tname.txt");
            }

            foreach (var name in names)
            {
                await File.WriteAllTextAsync(Path.Combine(repositoryPath, name), "original\n");
            }

            if (tracked)
            {
                await RunGitAsync(runner, repositoryPath, "add", "-A");
            }

            var builder = new GitSnapshotBuilder(runner);
            var initial = await builder.BuildAsync(repositoryPath);

            Assert.True(initial.Succeeded, initial.Diagnostic);

            var previous = Assert.IsType<Codelaxy.Contracts.Snapshot>(initial.Snapshot);

            foreach (var name in names)
            {
                await File.AppendAllTextAsync(Path.Combine(repositoryPath, name), "changed\n");

                var result = await builder.BuildAsync(repositoryPath);

                Assert.True(result.Succeeded, $"Path '{name}': {result.Diagnostic}");

                var current = Assert.IsType<Codelaxy.Contracts.Snapshot>(result.Snapshot);

                Assert.Equal(previous.HeadFingerprint, current.HeadFingerprint);
                Assert.Equal(previous.IndexFingerprint, current.IndexFingerprint);
                Assert.Equal(previous.StagedFingerprint, current.StagedFingerprint);

                Assert.NotEqual(previous.WorkingTreeFingerprint, current.WorkingTreeFingerprint);

                previous = current;
            }
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), $"Codelaxy F1 Special {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);
        return path;
    }

    [LinuxOnlyTheory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task BuildAsync_AcceptsLineFeedPathOnLinux(bool tracked)
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "README.md"), "baseline\n");

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
                "F1 LF fixture"
            );

            // Capture the state before introducing the LF path.
            var builder = new GitSnapshotBuilder(runner);
            var baseline = await builder.BuildAsync(repositoryPath);

            Assert.True(baseline.Succeeded, baseline.Diagnostic);
            Assert.NotNull(baseline.Snapshot);

            // A real LF character inside a filename.
            var name = "line\nbreak.txt";

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, name), "payload\n");

            if (tracked)
            {
                await RunGitAsync(runner, repositoryPath, "add", "--", name);
            }

            // The LF path must be accepted and observed.
            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.NotNull(result.Snapshot);

            // The new path must affect the working-tree fingerprint.
            Assert.NotEqual(
                baseline.Snapshot.WorkingTreeFingerprint,
                result.Snapshot.WorkingTreeFingerprint
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
