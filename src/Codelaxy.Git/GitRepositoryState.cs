namespace Codelaxy.Git;

public sealed record GitRepositoryState(
    string Head,
    string? Branch,
    bool IsInsideWorkTree,
    bool IsBare);
