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

        var rejection = await GetWorkTreeRejectionAsync(startDirectory, cancellationToken);

        if (rejection is not null)
        {
            return rejection;
        }

        return await ReadRepositoryPathsAsync(startDirectory, cancellationToken);
    }

    private async Task<GitRepositoryDiscoveryResult?> GetWorkTreeRejectionAsync(
        string startDirectory,
        CancellationToken cancellationToken
    )
    {
        var workTreeResult = await _runner.RunReadOnlyAsync(
            startDirectory,
            ["rev-parse", "--is-inside-work-tree"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!workTreeResult.Succeeded)
        {
            if (workTreeResult.FailureKind != GitCommandFailureKind.None)
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

        if (IsGitTrue(bareResult.StandardOutput))
        {
            return new GitRepositoryDiscoveryResult(
                null,
                GitRepositoryDiscoveryFailureKind.BareRepository,
                "The requested Git repository is bare and has no worktree."
            );
        }

        if (!IsGitTrue(workTreeResult.StandardOutput))
        {
            return new GitRepositoryDiscoveryResult(
                null,
                GitRepositoryDiscoveryFailureKind.NotRepository,
                "The requested directory is not inside a Git worktree."
            );
        }

        return null;
    }

    private async Task<GitRepositoryDiscoveryResult> ReadRepositoryPathsAsync(
        string startDirectory,
        CancellationToken cancellationToken
    )
    {
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
            RemoveGitLineTerminator(topLevelResult.StandardOutput),
            RemoveGitLineTerminator(gitDirectoryResult.StandardOutput),
            RemoveGitLineTerminator(gitCommonDirectoryResult.StandardOutput)
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

    private static bool IsGitTrue(string output)
    {
        return string.Equals(output.Trim(), "true", StringComparison.OrdinalIgnoreCase);
    }

    internal static string RemoveGitLineTerminator(string output)
    {
        if (OperatingSystem.IsWindows() && output.EndsWith("\r\n", StringComparison.Ordinal))
        {
            return output[..^2];
        }

        return output.EndsWith('\n') ? output[..^1] : output;
    }
}
