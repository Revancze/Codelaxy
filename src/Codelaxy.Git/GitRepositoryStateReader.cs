namespace Codelaxy.Git;

public sealed class GitRepositoryStateReader
{
    private readonly GitProcessRunner _runner;

    public GitRepositoryStateReader(GitProcessRunner runner)
    {
        ArgumentNullException.ThrowIfNull(runner);

        _runner = runner;
    }

    public async Task<GitRepositoryState> ReadAsync(
        string repositoryPath,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(repositoryPath);

        var headResult = await _runner.RunAsync(
            repositoryPath,
            ["rev-parse", "HEAD"],
            cancellationToken);

        if (!headResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git HEAD: {headResult.StandardError.Trim()}");
        }

        var branchResult = await _runner.RunAsync(
            repositoryPath,
            ["branch", "--show-current"],
            cancellationToken);

        if (!branchResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git branch: {branchResult.StandardError.Trim()}");
        }

        var workTreeResult = await _runner.RunAsync(
            repositoryPath,
            ["rev-parse", "--is-inside-work-tree"],
            cancellationToken);

        if (!workTreeResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git worktree state: {workTreeResult.StandardError.Trim()}");
        }

        var bareResult = await _runner.RunAsync(
            repositoryPath,
            ["rev-parse", "--is-bare-repository"],
            cancellationToken);

        if (!bareResult.Succeeded)
        {
            throw new InvalidOperationException(
                $"Unable to read Git bare state: {bareResult.StandardError.Trim()}");
        }

        var branch = branchResult.StandardOutput.Trim();

        return new GitRepositoryState(
            headResult.StandardOutput.Trim(),
            string.IsNullOrEmpty(branch) ? null : branch,
            bool.Parse(workTreeResult.StandardOutput.Trim()),
            bool.Parse(bareResult.StandardOutput.Trim()));
    }
}
