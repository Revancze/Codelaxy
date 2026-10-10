using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitIndexEntryParserTests
{
    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    [Fact]
    public void Parse_PreservesModeObjectIdStageAndPath()
    {
        const string input =
            "100644 " + "0123456789abcdef0123456789abcdef01234567 " + "0\tpath/to/file.txt\0";

        var entries = GitIndexEntryParser.Parse(input);

        var entry = Assert.Single(entries);

        Assert.Equal("100644", entry.Mode);

        Assert.Equal("0123456789abcdef0123456789abcdef01234567", entry.ObjectId);

        Assert.Equal(0, entry.Stage);

        Assert.Equal("path/to/file.txt", entry.Path);
    }

    [Fact]
    public void Parse_PreservesMultipleStagesForSamePath()
    {
        const string input =
            "100644 "
            + "1111111111111111111111111111111111111111 "
            + "1\tconflict.txt\0"
            + "100644 "
            + "2222222222222222222222222222222222222222 "
            + "2\tconflict.txt\0"
            + "100644 "
            + "3333333333333333333333333333333333333333 "
            + "3\tconflict.txt\0";

        var entries = GitIndexEntryParser.Parse(input);

        Assert.Equal(3, entries.Count);

        Assert.Equal([1, 2, 3], entries.Select(entry => entry.Stage));

        Assert.All(entries, entry => Assert.Equal("conflict.txt", entry.Path));
    }

    [Fact]
    public void Parse_PreservesSkipWorktreeTag()
    {
        const string input =
            "S 100644 " + "0123456789abcdef0123456789abcdef01234567 " + "0\tpath/to/file.txt\0";

        var entry = Assert.Single(GitIndexEntryParser.Parse(input));

        Assert.Equal("100644", entry.Mode);
        Assert.Equal("0123456789abcdef0123456789abcdef01234567", entry.ObjectId);
        Assert.Equal(0, entry.Stage);
        Assert.Equal("path/to/file.txt", entry.Path);
        Assert.True(entry.SkipWorktree);
    }

    [Fact]
    public async Task Parse_PreservesStagesFromRealUnmergedIndex()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            var conflictPath = Path.Combine(repositoryPath, "conflict.txt");

            await File.WriteAllTextAsync(conflictPath, "base\n");

            await RunGitAsync(runner, repositoryPath, "add", "conflict.txt");

            await CommitAsync(runner, repositoryPath, "base");

            await RunGitAsync(runner, repositoryPath, "switch", "-c", "theirs");

            await File.WriteAllTextAsync(conflictPath, "theirs\n");

            await RunGitAsync(runner, repositoryPath, "add", "conflict.txt");

            await CommitAsync(runner, repositoryPath, "theirs");

            await RunGitAsync(runner, repositoryPath, "switch", "main");

            await File.WriteAllTextAsync(conflictPath, "ours\n");

            await RunGitAsync(runner, repositoryPath, "add", "conflict.txt");

            await CommitAsync(runner, repositoryPath, "ours");

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

            Assert.Equal(3, conflictEntries.Length);

            Assert.Equal([1, 2, 3], conflictEntries.Select(entry => entry.Stage));

            Assert.All(conflictEntries, entry => Assert.Equal("100644", entry.Mode));

            Assert.Equal(
                3,
                conflictEntries
                    .Select(entry => entry.ObjectId)
                    .Distinct(StringComparer.Ordinal)
                    .Count()
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

    private static async Task CommitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        string message
    )
    {
        await RunGitAsync(
            runner,
            repositoryPath,
            "-c",
            "user.name=Codelaxy Tests",
            "-c",
            "user.email=codelaxy@example.invalid",
            "commit",
            "-m",
            message
        );
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), $"Codelaxy Index Tests {Guid.NewGuid():N}");

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
