using Codelaxy.Git;

namespace Codelaxy.Tests;

[Collection("GitWrapperIsolation")]
public sealed class GitSnapshotInvalidSymlinkHashTests
{
    [LinuxOnlyTheory]
    [InlineData(true, false)]
    [InlineData(false, false)]
    [InlineData(true, true)]
    [InlineData(false, true)]
    public async Task BuildAsync_RejectsInvalidSymlinkOidEvenWhenGitExitsZero(
        bool tracked,
        bool invalidHex
    )
    {
        var repositoryPath = Path.Combine(
            Path.GetTempPath(),
            $"codelaxy-invalid-symlink-{Guid.NewGuid():N}"
        );

        var wrapperDirectory = Path.Combine(
            Path.GetTempPath(),
            $"codelaxy-invalid-git-{Guid.NewGuid():N}"
        );

        Directory.CreateDirectory(repositoryPath);
        Directory.CreateDirectory(wrapperDirectory);

        try
        {
            var setupRunner = new GitProcessRunner();

            await RunGitAsync(setupRunner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "a.txt"), "alpha\n");

            await RunGitAsync(setupRunner, repositoryPath, "add", "a.txt");

            var linkPath = Path.Combine(repositoryPath, "b.link");

            if (tracked)
            {
                File.CreateSymbolicLink(linkPath, "a.txt");

                await RunGitAsync(setupRunner, repositoryPath, "add", "b.link");
            }

            await RunGitAsync(
                setupRunner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "initial"
            );

            if (!tracked)
            {
                File.CreateSymbolicLink(linkPath, "a.txt");
            }

            var wrapperPath = Path.Combine(wrapperDirectory, "git-invalid-oid-wrapper.sh");

            var wrapperScript =
                "#!/bin/sh\n"
                + "if [ \"$#\" -ge 4 ] "
                + "&& [ \"$1\" = \"-C\" ] "
                + "&& [ \"$3\" = \"hash-object\" ] "
                + "&& [ \"$4\" = \"--stdin\" ]; then\n"
                + "    : > \"${0}.hit\"\n"
                + "    cat > /dev/null\n"
                + (invalidHex ? "    printf 'not-an-oid\\n'\n" : "")
                + "    exit 0\n"
                + "fi\n"
                + "exec git \"$@\"\n";

            await File.WriteAllTextAsync(wrapperPath, wrapperScript);
            if (!OperatingSystem.IsLinux())
            {
                throw new PlatformNotSupportedException(
                    "This test requires Linux filesystem semantics."
                );
            }
            var mode = File.GetUnixFileMode(wrapperPath);

            File.SetUnixFileMode(
                wrapperPath,
                mode
                    | UnixFileMode.UserExecute
                    | UnixFileMode.GroupExecute
                    | UnixFileMode.OtherExecute
            );

            var runner = new GitProcessRunner(wrapperPath);
            var builder = new GitSnapshotBuilder(runner);

            var result = await builder.BuildAsync(repositoryPath);

            Assert.True(
                File.Exists(wrapperPath + ".hit"),
                "Fake Git did not intercept symlink hashing."
            );

            Assert.False(
                result.Succeeded,
                "Invalid symlink OID must not produce a successful snapshot."
            );

            Assert.Null(result.Snapshot);

            Assert.True(
                result.Diagnostic.Contains("invalid", StringComparison.OrdinalIgnoreCase),
                "Expected invalid symlink OID diagnostic.\n"
                    + $"Tracked: {tracked}\n"
                    + $"InvalidHex: {invalidHex}\n"
                    + $"Actual diagnostic:\n{result.Diagnostic}"
            );
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
            Directory.Delete(wrapperDirectory, recursive: true);
        }
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
