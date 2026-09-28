namespace Codelaxy.Git;

public sealed class GitRepositoryDiscovery
{
    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    private readonly GitProcessRunner _runner;

    public GitRepositoryDiscovery(GitProcessRunner runner)
    {
        ArgumentNullException.ThrowIfNull(runner);

        _runner = runner;
    }

    public async Task<GitRepositoryDiscoveryResult> DiscoverAsync(
        string startDirectory,
        CancellationToken cancellationToken = default
    )
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(startDirectory);

        var workTreeResult = await _runner.RunReadOnlyAsync(
            startDirectory,
            ["rev-parse", "--is-inside-work-tree"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!workTreeResult.Succeeded)
        {
            if (workTreeResult.FailureKind == GitCommandFailureKind.LaunchFailure)
            {
                return CreateFailure(workTreeResult);
            }

            return new GitRepositoryDiscoveryResult(
                null,
                GitRepositoryDiscoveryFailureKind.NotRepository,
                "The requested directory is not inside a Git repository."
            );
        }

        var bareResult = await _runner.RunReadOnlyAsync(
            startDirectory,
            ["rev-parse", "--is-bare-repository"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!bareResult.Succeeded)
        {
            return CreateFailure(bareResult);
        }

        if (
            string.Equals(
                bareResult.StandardOutput.Trim(),
                "true",
                StringComparison.OrdinalIgnoreCase
            )
        )
        {
            return new GitRepositoryDiscoveryResult(
                null,
                GitRepositoryDiscoveryFailureKind.BareRepository,
                "The requested Git repository is bare and has no worktree."
            );
        }

        if (
            !string.Equals(
                workTreeResult.StandardOutput.Trim(),
                "true",
                StringComparison.OrdinalIgnoreCase
            )
        )
        {
            return new GitRepositoryDiscoveryResult(
                null,
                GitRepositoryDiscoveryFailureKind.NotRepository,
                "The requested directory is not inside a Git worktree."
            );
        }

        var topLevelResult = await _runner.RunReadOnlyAsync(
            startDirectory,
            ["rev-parse", "--show-toplevel"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!topLevelResult.Succeeded)
        {
            return CreateFailure(topLevelResult);
        }

        var gitDirectoryResult = await _runner.RunReadOnlyAsync(
            startDirectory,
            ["rev-parse", "--absolute-git-dir"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!gitDirectoryResult.Succeeded)
        {
            return CreateFailure(gitDirectoryResult);
        }

        var gitCommonDirectoryResult = await _runner.RunReadOnlyAsync(
            startDirectory,
            ["rev-parse", "--path-format=absolute", "--git-common-dir"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!gitCommonDirectoryResult.Succeeded)
        {
            return CreateFailure(gitCommonDirectoryResult);
        }

        var repository = new GitRepository(
            topLevelResult.StandardOutput.Trim(),
            gitDirectoryResult.StandardOutput.Trim(),
            gitCommonDirectoryResult.StandardOutput.Trim()
        );

        return new GitRepositoryDiscoveryResult(
            repository,
            GitRepositoryDiscoveryFailureKind.None,
            string.Empty
        );
    }

    public async Task<GitRepository?> TryDiscoverAsync(
        string startDirectory,
        CancellationToken cancellationToken = default
    )
    {
        var result = await DiscoverAsync(startDirectory, cancellationToken);

        return result.Repository;
    }

    private static GitRepositoryDiscoveryResult CreateFailure(GitCommandResult result)
    {
        if (result.FailureKind == GitCommandFailureKind.LaunchFailure)
        {
            return new GitRepositoryDiscoveryResult(
                null,
                GitRepositoryDiscoveryFailureKind.LaunchFailure,
                result.StandardError
            );
        }

        return new GitRepositoryDiscoveryResult(
            null,
            GitRepositoryDiscoveryFailureKind.CommandFailure,
            result.StandardError
        );
    }
}
