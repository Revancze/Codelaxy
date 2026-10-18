using Codelaxy.Git;

namespace Codelaxy.Tests;

// Shared Git configuration for deterministic Golden test fixtures.
// This does not replace the production GitProcessRunner.
internal static class GoldenGitFixture
{
    public static async Task InitializeSha1Async(GitProcessRunner runner, string repositoryPath)
    {
        var templateDirectory = Path.Combine(repositoryPath, ".codelaxy-empty-template");

        var hooksDirectory = Path.Combine(repositoryPath, ".git", "codelaxy-empty-hooks");

        var excludesPath = Path.Combine(repositoryPath, ".git", "codelaxy-empty-excludes");

        var attributesPath = Path.Combine(repositoryPath, ".git", "codelaxy-empty-attributes");

        Directory.CreateDirectory(templateDirectory);

        try
        {
            // Protection must exist before git init:
            // init itself can execute reference-transaction hooks.
            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                $"core.hooksPath={hooksDirectory}",
                "-c",
                "core.fsmonitor=false",
                "init",
                "-q",
                "--object-format=sha1",
                "-b",
                "main",
                $"--template={templateDirectory}"
            );
        }
        finally
        {
            Directory.Delete(templateDirectory);
        }

        Directory.CreateDirectory(hooksDirectory);
        await File.WriteAllTextAsync(excludesPath, "");

        await File.WriteAllTextAsync(attributesPath, "");

        await RunGitAsync(
            runner,
            repositoryPath,
            "config",
            "--local",
            "core.hooksPath",
            hooksDirectory
        );

        await RunGitAsync(runner, repositoryPath, "config", "--local", "core.fsmonitor", "false");

        await RunGitAsync(
            runner,
            repositoryPath,
            "config",
            "--local",
            "core.excludesFile",
            excludesPath
        );

        await RunGitAsync(
            runner,
            repositoryPath,
            "config",
            "--local",
            "core.attributesFile",
            attributesPath
        );

        await RunGitAsync(runner, repositoryPath, "config", "--local", "merge.ff", "true");

        await RunGitAsync(
            runner,
            repositoryPath,
            "config",
            "--local",
            "merge.verifySignatures",
            "false"
        );

        await RunGitAsync(runner, repositoryPath, "config", "--local", "core.autocrlf", "false");
    }

    private static async Task RunGitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments
    )
    {
        var result = await runner.RunAsync(repositoryPath, arguments, TimeSpan.FromSeconds(30));

        Assert.True(result.Succeeded, $"git {string.Join(' ', arguments)}: {result.StandardError}");
    }
}
