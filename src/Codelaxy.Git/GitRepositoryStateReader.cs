namespace Codelaxy.Git;

public sealed class GitRepositoryStateReader
{
    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    private readonly GitProcessRunner _runner;

    public GitRepositoryStateReader(GitProcessRunner runner)
    {
        ArgumentNullException.ThrowIfNull(runner);

        _runner = runner;
    }

    public async Task<GitRepositoryState> ReadAsync(
        string repositoryPath,
        CancellationToken cancellationToken = default
    )
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(repositoryPath);

        var headResult = await _runner.RunReadOnlyAsync(
            repositoryPath,
            ["rev-parse", "HEAD"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!headResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git HEAD: {headResult.StandardError.Trim()}"
            );
        }

        var branchResult = await _runner.RunReadOnlyAsync(
            repositoryPath,
            ["branch", "--show-current"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!branchResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git branch: {branchResult.StandardError.Trim()}"
            );
        }

        var workTreeResult = await _runner.RunReadOnlyAsync(
            repositoryPath,
            ["rev-parse", "--is-inside-work-tree"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!workTreeResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git worktree state: {workTreeResult.StandardError.Trim()}"
            );
        }

        var bareResult = await _runner.RunReadOnlyAsync(
            repositoryPath,
            ["rev-parse", "--is-bare-repository"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!bareResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git bare state: {bareResult.StandardError.Trim()}"
            );
        }

        var branch = branchResult.StandardOutput.Trim();

        return new GitRepositoryState(
            headResult.StandardOutput.Trim(),
            string.IsNullOrEmpty(branch) ? null : branch,
            bool.Parse(workTreeResult.StandardOutput.Trim()),
            bool.Parse(bareResult.StandardOutput.Trim())
        );
    }
}
