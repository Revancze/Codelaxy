using System.Diagnostics;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// G2: Linux file names that are not valid UTF-8 decode to U+FFFD in .NET, so
// distinct names (and symlink targets) can collapse into one string.
public class GitSnapshotInvalidUtf8Tests
{
    private const string InvalidByteName = "$(printf '\\377')";
    private const string OtherInvalidByteName = "$(printf '\\376')";
    private const string ReplacementCharacterName = "$(printf '\\357\\277\\275')";
    private const string ExpectedDiagnostic = "not valid UTF-8";

    [Fact]
    public async Task BuildAsync_RejectsUntrackedPathWithInvalidUtf8OnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await InitializeRepositoryAsync(runner, repositoryPath);

            RunShell(repositoryPath, $"printf 'content\\n' > \"{InvalidByteName}\"");

            // Proof that the name on disk really is the single byte 0xFF.
            Assert.Contains("ff 00", ListRawNameBytes(repositoryPath));

            var result = await new GitSnapshotBuilder(runner).BuildAsync(repositoryPath);

            AssertRefused(result);
        }
        finally
        {
            DeleteDirectoryNatively(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_DoesNotMergeInvalidUtf8NameWithReplacementCharacterNameOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await InitializeRepositoryAsync(runner, repositoryPath);

            // A genuine U+FFFD name (EF BF BD) next to an invalid one (FF).
            RunShell(
                repositoryPath,
                $"printf 'valid\\n' > \"{ReplacementCharacterName}\"; printf 'one\\n' > \"{InvalidByteName}\""
            );

            var rawNames = ListRawNameBytes(repositoryPath);
            Assert.Contains("ff 00", rawNames);
            Assert.Contains("ef bf bd 00", rawNames);

            var builder = new GitSnapshotBuilder(runner);

            var first = await builder.BuildAsync(repositoryPath);

            RunShell(repositoryPath, $"printf 'two\\n' > \"{InvalidByteName}\"");

            var second = await builder.BuildAsync(repositoryPath);

            AssertRefusedOrDistinct(first, second);
        }
        finally
        {
            DeleteDirectoryNatively(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_DoesNotMergeSymlinkTargetsWithDifferentInvalidUtf8OnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await InitializeRepositoryAsync(runner, repositoryPath);

            RunShell(repositoryPath, $"ln -s \"{InvalidByteName}\" link");
            Assert.Equal("ff", ReadRawLinkTargetBytes(repositoryPath, "link"));

            var builder = new GitSnapshotBuilder(runner);

            var first = await builder.BuildAsync(repositoryPath);

            RunShell(repositoryPath, $"rm link && ln -s \"{OtherInvalidByteName}\" link");
            Assert.Equal("fe", ReadRawLinkTargetBytes(repositoryPath, "link"));

            var second = await builder.BuildAsync(repositoryPath);

            AssertRefusedOrDistinct(first, second);
        }
        finally
        {
            DeleteDirectoryNatively(repositoryPath);
        }
    }

    // Every refusal carries the expected diagnostic and no snapshot; every success
    // carries a snapshot; two successes must not share a working-tree identity.
    private static void AssertRefusedOrDistinct(
        GitSnapshotBuildResult first,
        GitSnapshotBuildResult second
    )
    {
        foreach (var result in new[] { first, second })
        {
            if (result.Succeeded)
            {
                Assert.NotNull(result.Snapshot);
            }
            else
            {
                AssertRefused(result);
            }
        }

        if (first.Succeeded && second.Succeeded)
        {
            Assert.NotEqual(
                first.Snapshot!.WorkingTreeFingerprint,
                second.Snapshot!.WorkingTreeFingerprint
            );
        }
    }

    private static void AssertRefused(GitSnapshotBuildResult result)
    {
        Assert.False(result.Succeeded);
        Assert.Null(result.Snapshot);
        Assert.Contains(ExpectedDiagnostic, result.Diagnostic, StringComparison.Ordinal);
    }

    private static async Task InitializeRepositoryAsync(
        GitProcessRunner runner,
        string repositoryPath
    )
    {
        await RunGitAsync(runner, repositoryPath, "init", "-b", "main");
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "tracked.txt"), "committed\n");
        await RunGitAsync(runner, repositoryPath, "add", "tracked.txt");
        await RunGitAsync(
            runner,
            repositoryPath,
            "-c",
            "user.name=Codelaxy Tests",
            "-c",
            "user.email=codelaxy@example.invalid",
            "commit",
            "-m",
            "initial"
        );
    }

    private static void RunShell(string workingDirectory, string script)
    {
        using var process = Process.Start(
            new ProcessStartInfo("sh", ["-c", script]) { WorkingDirectory = workingDirectory }
        )!;

        process.WaitForExit();

        Assert.Equal(0, process.ExitCode);
    }

    private static string ListRawNameBytes(string workingDirectory) =>
        ReadShellOutputBytes(
            workingDirectory,
            "find . -mindepth 1 -maxdepth 1 -printf '%f\\0' | od -An -tx1"
        );

    private static string ReadRawLinkTargetBytes(string workingDirectory, string link) =>
        ReadShellOutputBytes(workingDirectory, $"readlink -n -- '{link}' | od -An -tx1");

    private static string ReadShellOutputBytes(string workingDirectory, string script)
    {
        using var process = Process.Start(
            new ProcessStartInfo("sh", ["-c", script])
            {
                WorkingDirectory = workingDirectory,
                RedirectStandardOutput = true,
            }
        )!;

        var text = process.StandardOutput.ReadToEnd();

        process.WaitForExit();
        Assert.Equal(0, process.ExitCode);

        return string.Join(' ', text.Split([' ', '\n'], StringSplitOptions.RemoveEmptyEntries));
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

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), $"Codelaxy G2 Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }

    // .NET cannot delete a name it decodes to U+FFFD; remove the tree natively.
    private static void DeleteDirectoryNatively(string path)
    {
        using var process = Process.Start("rm", ["-rf", "--", path])!;

        process.WaitForExit();
        Assert.Equal(0, process.ExitCode);
    }
}
