using System.Text;
using Codelaxy.Contracts;

namespace Codelaxy.Tests;

public class SnapshotSerializerTests
{
    [Fact]
    public void Deserialize_RejectsUnknownSchemaVersion()
    {
        var input =
            Encoding.UTF8.GetBytes(
                """
                {"recordType":"snapshot","schemaVersion":2,"headFingerprint":"sha256:head","indexFingerprint":"sha256:index","workingTreeFingerprint":"sha256:worktree","stagedFingerprint":"sha256:staged"}
                """);

        Assert.Throws<FormatException>(
            () =>
                SnapshotSerializer.Deserialize(input));
    }

    [Fact]
    public void Serialize_IsDeterministicAndRoundTrips()
    {
        var snapshot = new Snapshot
        {
            SchemaVersion = 1,
            HeadFingerprint = "sha256:head",
            IndexFingerprint = "sha256:index",
            WorkingTreeFingerprint = "sha256:worktree",
            StagedFingerprint = "sha256:staged",
        };

        var first =
            SnapshotSerializer.Serialize(snapshot);

        var second =
            SnapshotSerializer.Serialize(snapshot);

        Assert.Equal(
            first,
            second);

        Assert.Equal(
            """
            {"recordType":"snapshot","schemaVersion":1,"headFingerprint":"sha256:head","indexFingerprint":"sha256:index","workingTreeFingerprint":"sha256:worktree","stagedFingerprint":"sha256:staged"}
            """,
            Encoding.UTF8.GetString(first));

        var roundTripped =
            SnapshotSerializer.Deserialize(first);

        Assert.Equal(
            snapshot,
            roundTripped);
    }

    [Fact]
    public void Deserialize_RejectsUnknownRecordType()
    {
        var input =
            Encoding.UTF8.GetBytes(
                """
                {"recordType":"warp-core","schemaVersion":1,"headFingerprint":"sha256:head","indexFingerprint":"sha256:index","workingTreeFingerprint":"sha256:worktree","stagedFingerprint":"sha256:staged"}
                """);

        Assert.Throws<FormatException>(
            () =>
                SnapshotSerializer.Deserialize(input));
    }
}
