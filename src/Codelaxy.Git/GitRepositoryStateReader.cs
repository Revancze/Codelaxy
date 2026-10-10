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

    public async Task<GitRepositoryStateReadResult> ReadAsync(
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
            return Failure("Unable to read Git HEAD", headResult);
        }

        var branchResult = await _runner.RunReadOnlyAsync(
            repositoryPath,
            ["branch", "--show-current"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!branchResult.Succeeded)
        {
            return Failure("Unable to read Git branch", branchResult);
        }

        var workTreeResult = await _runner.RunReadOnlyAsync(
            repositoryPath,
            ["rev-parse", "--is-inside-work-tree"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!workTreeResult.Succeeded)
        {
            return Failure("Unable to read Git worktree state", workTreeResult);
        }

        var bareResult = await _runner.RunReadOnlyAsync(
            repositoryPath,
            ["rev-parse", "--is-bare-repository"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!bareResult.Succeeded)
        {
            return Failure("Unable to read Git bare state", bareResult);
        }

        var branch = branchResult.StandardOutput.Trim();

        var state = new GitRepositoryState(
            headResult.StandardOutput.Trim(),
            string.IsNullOrEmpty(branch) ? null : branch,
            bool.Parse(workTreeResult.StandardOutput.Trim()),
            bool.Parse(bareResult.StandardOutput.Trim())
        );

        return new GitRepositoryStateReadResult(state, string.Empty);
    }

    private static GitRepositoryStateReadResult Failure(string prefix, GitCommandResult result)
    {
        var detail = result.StandardError.Trim();

        var diagnostic = string.IsNullOrWhiteSpace(detail) ? prefix : $"{prefix}: {detail}";

        return new GitRepositoryStateReadResult(null, diagnostic);
    }
}
