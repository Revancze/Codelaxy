namespace Codelaxy.Git;

public sealed record GitRepositoryStateReadResult(GitRepositoryState? State, string Diagnostic)
{
    public bool Succeeded => State is not null;
}
