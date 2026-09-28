using Codelaxy.Contracts;

namespace Codelaxy.Tests;

public class SnapshotTests
{
    [Fact]
    public void Snapshot_StoresIndependentRepositoryFingerprints()
    {
        var snapshot = new Snapshot
        {
            SchemaVersion = 1,
            HeadFingerprint = "head",
            IndexFingerprint = "index",
            WorkingTreeFingerprint = "worktree",
            StagedFingerprint = "staged",
        };

        Assert.Equal(1, snapshot.SchemaVersion);
        Assert.Equal("head", snapshot.HeadFingerprint);
        Assert.Equal("index", snapshot.IndexFingerprint);
        Assert.Equal(
            "worktree",
            snapshot.WorkingTreeFingerprint);
        Assert.Equal(
            "staged",
            snapshot.StagedFingerprint);
    }

    [Theory]
    [InlineData("", "index", "worktree", "staged")]
    [InlineData("head", " ", "worktree", "staged")]
    [InlineData("head", "index", null, "staged")]
    [InlineData("head", "index", "worktree", "")]
    public void Snapshot_RejectsEmptyFingerprints(
        string? head,
        string? index,
        string? worktree,
        string? staged)
    {
        Assert.ThrowsAny<ArgumentException>(
            () => new Snapshot
            {
                SchemaVersion = 1,
                HeadFingerprint = head!,
                IndexFingerprint = index!,
                WorkingTreeFingerprint = worktree!,
                StagedFingerprint = staged!,
            });
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Snapshot_RejectsInvalidSchemaVersion(
        int schemaVersion)
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => new Snapshot
            {
                SchemaVersion = schemaVersion,
                HeadFingerprint = "head",
                IndexFingerprint = "index",
                WorkingTreeFingerprint = "worktree",
                StagedFingerprint = "staged",
            });
    }
}
