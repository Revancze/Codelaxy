namespace Codelaxy.Git;

public sealed class GitRepositoryDiscovery
{
    private readonly GitProcessRunner _runner;

    public GitRepositoryDiscovery(GitProcessRunner runner)
    {
        ArgumentNullException.ThrowIfNull(runner);

        _runner = runner;
    }

    public async Task<GitRepositoryDiscoveryResult> DiscoverAsync(
        string startDirectory,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(startDirectory);

        var topLevelResult = await _runner.RunAsync(
            startDirectory,
            ["rev-parse", "--show-toplevel"],
            cancellationToken);

        if (!topLevelResult.Succeeded)
        {
            return CreateFailure(topLevelResult);
        }

        var gitDirectoryResult = await _runner.RunAsync(
            startDirectory,
            ["rev-parse", "--absolute-git-dir"],
            cancellationToken);

        if (!gitDirectoryResult.Succeeded)
        {
            return CreateFailure(gitDirectoryResult);
        }

        var gitCommonDirectoryResult = await _runner.RunAsync(
            startDirectory,
            [
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir"
            ],
            cancellationToken);

        if (!gitCommonDirectoryResult.Succeeded)
        {
            return CreateFailure(gitCommonDirectoryResult);
        }

        var repository = new GitRepository(
            topLevelResult.StandardOutput.Trim(),
            gitDirectoryResult.StandardOutput.Trim(),
            gitCommonDirectoryResult.StandardOutput.Trim());

        return new GitRepositoryDiscoveryResult(
            repository,
            GitRepositoryDiscoveryFailureKind.None,
            string.Empty);
    }

    public async Task<GitRepository?> TryDiscoverAsync(
        string startDirectory,
        CancellationToken cancellationToken = default)
    {
        var result = await DiscoverAsync(
            startDirectory,
            cancellationToken);

        return result.Repository;
    }

    private static GitRepositoryDiscoveryResult CreateFailure(
        GitCommandResult result)
    {
        if (result.FailureKind == GitCommandFailureKind.LaunchFailure)
        {
            return new GitRepositoryDiscoveryResult(
                null,
                GitRepositoryDiscoveryFailureKind.LaunchFailure,
                result.StandardError);
        }

        return new GitRepositoryDiscoveryResult(
            null,
            GitRepositoryDiscoveryFailureKind.CommandFailure,
            result.StandardError);
    }
}
