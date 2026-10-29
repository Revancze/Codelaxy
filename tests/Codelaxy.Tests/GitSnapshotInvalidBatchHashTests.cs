using Codelaxy.Git;

namespace Codelaxy.Tests;

[Collection("GitWrapperIsolation")]
public sealed class GitSnapshotInvalidBatchHashTests
{
    [LinuxOnlyTheory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task BuildAsync_RejectsTruncatedBatchOidOutput(bool tracked)
    {
        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException();
        }

        var repositoryPath = Path.Combine(
            Path.GetTempPath(),
            $"codelaxy-batch-oid-{Guid.NewGuid():N}"
        );

        var wrapperDirectory = Path.Combine(
            Path.GetTempPath(),
            $"codelaxy-batch-wrapper-{Guid.NewGuid():N}"
        );

        Directory.CreateDirectory(repositoryPath);
        Directory.CreateDirectory(wrapperDirectory);

        try
        {
            var realGit = new GitProcessRunner();
            await RunGitAsync(realGit, repositoryPath, "init", "-b", "main");

            if (tracked)
            {
                await CreateFixtureFilesAsync(repositoryPath);
                await RunGitAsync(realGit, repositoryPath, "add", "a.txt", "c.txt");
            }

            await RunGitAsync(
                realGit,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "initial"
            );

            if (!tracked)
            {
                await CreateFixtureFilesAsync(repositoryPath);
            }

            // First prove that the fixture works with real Git.
            var baseline = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);

            Assert.True(baseline.Succeeded, baseline.Diagnostic);
            Assert.NotNull(baseline.Snapshot);

            var wrapperPath = Path.Combine(wrapperDirectory, "git-truncated-batch-wrapper.sh");

            const string wrapperScript =
                "#!/bin/sh\n"
                + "if [ \"$#\" -ge 5 ] "
                + "&& [ \"$1\" = \"-C\" ] "
                + "&& [ \"$3\" = \"hash-object\" ] "
                + "&& [ \"$4\" = \"--no-filters\" ] "
                + "&& [ \"$5\" = \"--stdin-paths\" ]; then\n"
                + "    : > \"${0}.hit\"\n"
                + "    cat > \"${0}.stdin\"\n"
                + "    printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'\n"
                + "    exit 0\n"
                + "fi\n"
                + "exec git \"$@\"\n";

            await File.WriteAllTextAsync(wrapperPath, wrapperScript);

            File.SetUnixFileMode(
                wrapperPath,
                File.GetUnixFileMode(wrapperPath)
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            var builder = new GitSnapshotBuilder(new GitProcessRunner(wrapperPath));

            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(
                File.Exists(wrapperPath + ".hit"),
                "Fake Git did not intercept batch hashing."
            );

            Assert.Equal(2, (await File.ReadAllLinesAsync(wrapperPath + ".stdin")).Length);

            Assert.False(result.Succeeded);
            Assert.Null(result.Snapshot);

            Assert.Contains(
                tracked
                    ? "invalid tracked working-tree object hashes"
                    : "invalid untracked object hashes",
                result.Diagnostic,
                StringComparison.Ordinal
            );
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
            Directory.Delete(wrapperDirectory, recursive: true);
        }
    }

    private static async Task CreateFixtureFilesAsync(string repositoryPath)
    {
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "a.txt"), "alpha\n");

        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "c.txt"), "charlie\n");
    }

    private static async Task RunGitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments
    )
    {
        var result = await runner.RunAsync(repositoryPath, arguments);
        Assert.True(result.Succeeded, result.StandardError);
    }
}
