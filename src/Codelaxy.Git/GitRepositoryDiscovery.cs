namespace Codelaxy.Git;

public sealed class GitRepositoryDiscovery
{
    private readonly GitProcessRunner _runner;

    public GitRepositoryDiscovery(GitProcessRunner runner)
    {
        ArgumentNullException.ThrowIfNull(runner);

        _runner = runner;
    }

    public async Task<GitRepository?> TryDiscoverAsync(
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
            return null;
        }

        var gitDirectoryResult = await _runner.RunAsync(
            startDirectory,
            ["rev-parse", "--absolute-git-dir"],
            cancellationToken);

        if (!gitDirectoryResult.Succeeded)
        {
            return null;
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
            return null;
        }

        return new GitRepository(
            topLevelResult.StandardOutput.Trim(),
            gitDirectoryResult.StandardOutput.Trim(),
            gitCommonDirectoryResult.StandardOutput.Trim());
    }
}
