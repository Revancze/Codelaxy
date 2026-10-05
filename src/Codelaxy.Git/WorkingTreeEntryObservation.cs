namespace Codelaxy.Git;

internal sealed record WorkingTreeEntryObservation(
    string Path,
    WorkingTreeEntryKind Kind,
    string? Mode
);
