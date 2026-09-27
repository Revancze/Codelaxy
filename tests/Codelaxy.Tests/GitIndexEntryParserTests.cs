using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitIndexEntryParserTests
{
    [Fact]
    public void Parse_PreservesModeObjectIdStageAndPath()
    {
        const string input =
            "100644 " +
            "0123456789abcdef0123456789abcdef01234567 " +
            "0\tpath/to/file.txt\0";

        var entries =
            GitIndexEntryParser.Parse(input);

        var entry =
            Assert.Single(entries);

        Assert.Equal(
            "100644",
            entry.Mode);

        Assert.Equal(
            "0123456789abcdef0123456789abcdef01234567",
            entry.ObjectId);

        Assert.Equal(
            0,
            entry.Stage);

        Assert.Equal(
            "path/to/file.txt",
            entry.Path);
    }

    [Fact]
    public void Parse_PreservesMultipleStagesForSamePath()
    {
        const string input =
            "100644 " +
            "1111111111111111111111111111111111111111 " +
            "1\tconflict.txt\0" +
            "100644 " +
            "2222222222222222222222222222222222222222 " +
            "2\tconflict.txt\0" +
            "100644 " +
            "3333333333333333333333333333333333333333 " +
            "3\tconflict.txt\0";

        var entries =
            GitIndexEntryParser.Parse(input);

        Assert.Equal(
            3,
            entries.Count);

        Assert.Equal(
            [1, 2, 3],
            entries.Select(entry => entry.Stage));

        Assert.All(
            entries,
            entry =>
                Assert.Equal(
                    "conflict.txt",
                    entry.Path));
    }
}