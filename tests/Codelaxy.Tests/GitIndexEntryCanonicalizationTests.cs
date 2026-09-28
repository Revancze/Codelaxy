using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitIndexEntryCanonicalizationTests
{
    [Fact]
    public void Canonicalize_IsIndependentOfInputOrder()
    {
        var first =
            new[]
            {
                new GitIndexEntry(
                    "100644",
                    "2222222222222222222222222222222222222222",
                    0,
                    "b.txt"),

                new GitIndexEntry(
                    "100644",
                    "1111111111111111111111111111111111111111",
                    0,
                    "a.txt"),
            };

        var second =
            new[]
            {
                first[1],
                first[0],
            };

        var firstCanonical =
            GitIndexEntryCanonicalizer.Canonicalize(first);

        var secondCanonical =
            GitIndexEntryCanonicalizer.Canonicalize(second);

        Assert.Equal(
            firstCanonical,
            secondCanonical);
    }

    [Fact]
    public void Canonicalize_PreservesDistinctConflictStages()
    {
        var entries =
            new[]
            {
                new GitIndexEntry(
                    "100644",
                    "3333333333333333333333333333333333333333",
                    3,
                    "conflict.txt"),

                new GitIndexEntry(
                    "100644",
                    "1111111111111111111111111111111111111111",
                    1,
                    "conflict.txt"),

                new GitIndexEntry(
                    "100644",
                    "2222222222222222222222222222222222222222",
                    2,
                    "conflict.txt"),
            };

        var canonical =
            GitIndexEntryCanonicalizer.Canonicalize(entries);

        Assert.Equal(
            [
                "100644",
                "1111111111111111111111111111111111111111",
                "1",
                "conflict.txt",
                "100644",
                "2222222222222222222222222222222222222222",
                "2",
                "conflict.txt",
                "100644",
                "3333333333333333333333333333333333333333",
                "3",
                "conflict.txt",
            ],
            canonical);
    }
}
