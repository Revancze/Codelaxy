namespace Codelaxy.Git;

public sealed record GitIndexEntry(
    string Mode,
    string ObjectId,
    int Stage,
    string Path);