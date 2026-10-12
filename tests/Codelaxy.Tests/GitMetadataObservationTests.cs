using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitMetadataObservationTests
{
    [Theory]
    [InlineData("gitdir: C:/repo/.git\n", "C:/repo/.git")]
    [InlineData("gitdir: C:/repo/.git\r\n", "C:/repo/.git")]
    [InlineData("gitdir: C:/repo/.git", "C:/repo/.git")]
    public void Read_PreservesGitMetadataRules(string content, string expected)
    {
        using var fixture = new MetadataFixture();

        var path = fixture.Write(content);
        var result = GitMetadataObservation.Read(path, "gitdir: ");

        Assert.Equal(GitMetadataObservation.ReadStatus.Valid, result.Status);
        Assert.Equal(expected, result.Value);
    }

    [Theory]
    [InlineData("GITDIR: C:/repo/.git\n")]
    [InlineData(" gitdir: C:/repo/.git\n")]
    [InlineData("gitdir:C:/repo/.git\n")]
    [InlineData("")]
    public void Read_RejectsInvalidMetadata(string content)
    {
        using var fixture = new MetadataFixture();

        var result = GitMetadataObservation.Read(fixture.Write(content), "gitdir: ");

        Assert.Equal(GitMetadataObservation.ReadStatus.Invalid, result.Status);
        Assert.Null(result.Value);
    }

    [Fact]
    public void Read_ReportsMissingMetadata()
    {
        using var fixture = new MetadataFixture();

        var result = GitMetadataObservation.Read(Path.Combine(fixture.Root, "missing"), "gitdir: ");

        Assert.Equal(GitMetadataObservation.ReadStatus.Missing, result.Status);
    }

    [Fact]
    public void Read_ReportsLockedMetadataAsIndeterminateOnWindows()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MetadataFixture();

        var path = fixture.Write("gitdir: C:/repo/.git\n");

        using var lockedFile = new FileStream(
            path,
            FileMode.Open,
            FileAccess.ReadWrite,
            FileShare.None
        );

        var result = GitMetadataObservation.Read(path, "gitdir: ");

        Assert.Equal(GitMetadataObservation.ReadStatus.Indeterminate, result.Status);
        Assert.Null(result.Value);
    }

    private sealed class MetadataFixture : IDisposable
    {
        public MetadataFixture()
        {
            Root = Path.Combine(Path.GetTempPath(), $"Codelaxy Metadata {Guid.NewGuid():N}");

            Directory.CreateDirectory(Root);
        }

        public string Root { get; }

        public string Write(string content)
        {
            var path = Path.Combine(Root, "metadata");

            File.WriteAllText(path, content);

            return path;
        }

        public void Dispose()
        {
            Directory.Delete(Root, recursive: true);
        }
    }
}
