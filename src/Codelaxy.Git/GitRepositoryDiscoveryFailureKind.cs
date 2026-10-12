namespace Codelaxy.Git;

public enum GitRepositoryDiscoveryFailureKind
{
    None,
    LaunchFailure,
    NotRepository,
    BareRepository,
    CommandFailure,
}
