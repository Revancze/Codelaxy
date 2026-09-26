namespace Codelaxy.Git;

public sealed record GitRepositoryDiscoveryResult(
    GitRepository? Repository,
    GitRepositoryDiscoveryFailureKind FailureKind,
    string Diagnostic)
{
    public bool Succeeded =>
        Repository is not null &&
        FailureKind == GitRepositoryDiscoveryFailureKind.None;
}
