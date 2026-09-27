using Codelaxy.Contracts;

namespace Codelaxy.Git;

public sealed record GitSnapshotBuildResult(
    Snapshot? Snapshot,
    string Diagnostic)
{
    public bool Succeeded =>
        Snapshot is not null;
}