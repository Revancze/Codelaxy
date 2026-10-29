using System.Globalization;
using Codelaxy.Git;
using Xunit.Abstractions;

namespace Codelaxy.Tests;

// H1: git hash-object --stdin-paths ends before it has read all of its standard input
// (here: it cannot open the first path). BuildAsync must turn that into a controlled
// failure and must not let the IOException of the stdin write escape.
//
// What this builder-level test proves: no unhandled exception, Succeeded == false,
// Snapshot == null and a diagnostic about hashing. What it does NOT prove on its own:
// protection against a false success when Git exits with code 0 although the stdin write
// failed. Here Git exits non-zero ("could not open ..."), which BuildAsync already treats
// as a failure. That layer is covered by GitProcessRunnerTests
// (RunReadOnlyAsync_ClosedStdinWithLargePayload_NeverSucceeds, helper exit codes 0 and 17).
//
// The unreadable file sorts first, so Git stops at the very first path while the runner
// still has most of the payload to write.
public sealed class GitSnapshotHashingFailureTests(ITestOutputHelper output)
{
    private const string UnreadableName = "0-unreadable.txt";
    private const int PaddingFileCount = 1000;
    private const int PaddingNameLength = 120;

    // Lower bound for the real stdin payload (the paths as encoded by
    // GitObjectHasher.TryEncodePaths), calibrated by experiment on 2026-10-25 against the
    // M2 code without the M2a fix: on Linux 54 KB did not trigger H1 (0 of 6 runs), 81 KB
    // and 135 KB did (6 of 6 each); on Windows 200 paths (about 27 KB) already did.
    //
    // Limitation: more than 64 KiB is NOT a universal guarantee that the stdin write fails.
    // The effective pipe capacity depends on the operating system and its configuration
    // (Linux can resize pipes, Windows has its own buffer), on how much Git reads before it
    // gives up and on timing. The bound only stops the fixture from being shrunk silently;
    // the proof that this test can see H1 is the RED run against the code without M2a.
    private const int MinimumPayloadBytes = 128 * 1024;

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task BuildAsync_ReadableFilesAmongManyPaths_Succeeds(bool tracked)
    {
        var runner = new GitProcessRunner();
        var repositoryPath = await CreateRepositoryAsync(runner, tracked);

        try
        {
            var result = await new GitSnapshotBuilder(runner).BuildAsync(repositoryPath);

            Assert.True(result.Succeeded, $"CONTROL FAILED: {result.Diagnostic}");
            Assert.NotNull(result.Snapshot);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task BuildAsync_UnreadableFileAmongManyPaths_ReturnsFailureWithoutThrowing(
        bool tracked
    )
    {
        var runner = new GitProcessRunner();
        var repositoryPath = await CreateRepositoryAsync(runner, tracked);

        try
        {
            var payloadBytes = await AssertPayloadFillsThePipeAsync(
                runner,
                repositoryPath,
                tracked
            );

            output.WriteLine(
                $"stdin payload: {payloadBytes.ToString(CultureInfo.InvariantCulture)} bytes"
            );

            using var obstruction = Obstruction.Create(
                Path.Combine(repositoryPath, UnreadableName)
            );

            GitSnapshotBuildResult? result = null;

            var thrown = await Record.ExceptionAsync(async () =>
                result = await new GitSnapshotBuilder(runner).BuildAsync(repositoryPath)
            );

            Assert.True(
                thrown is null,
                $"H1: BuildAsync threw {thrown?.GetType().Name}: {thrown?.Message}"
            );

            Assert.NotNull(result);
            output.WriteLine($"diagnostic: {result.Diagnostic}");

            Assert.False(
                result.Succeeded,
                "H1: BuildAsync reported success for an unreadable file."
            );
            Assert.Null(result.Snapshot);
            Assert.False(
                string.IsNullOrWhiteSpace(result.Diagnostic),
                "H1: the diagnostic is empty."
            );
            Assert.Contains("hash", result.Diagnostic, StringComparison.OrdinalIgnoreCase);
            Assert.Contains(UnreadableName, result.Diagnostic, StringComparison.Ordinal);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    // Measures the bytes that BuildAsync really sends to `git hash-object --stdin-paths`
    // for this fixture: the paths Git lists, encoded by the production encoder.
    private static async Task<int> AssertPayloadFillsThePipeAsync(
        GitProcessRunner runner,
        string repositoryPath,
        bool tracked
    )
    {
        string[] arguments = tracked
            ? ["ls-files", "-z"]
            : ["ls-files", "-z", "--others", "--exclude-standard"];

        var listing = await runner.RunAsync(repositoryPath, arguments);

        Assert.True(listing.Succeeded, listing.StandardError);

        var paths = listing.StandardOutput.Split('\0', StringSplitOptions.RemoveEmptyEntries);

        var encoded = GitObjectHasher.TryEncodePaths(paths, out var payload, out var diagnostic);

        Assert.True(encoded, diagnostic);
        Assert.Equal(UnreadableName, paths[0]);
        Assert.True(
            payload.Length >= MinimumPayloadBytes,
            "The H1 fixture is too small: "
                + payload.Length.ToString(CultureInfo.InvariantCulture)
                + " payload bytes, at least "
                + MinimumPayloadBytes.ToString(CultureInfo.InvariantCulture)
                + " are required, otherwise the test could pass vacuously."
        );

        return payload.Length;
    }

    private static async Task<string> CreateRepositoryAsync(GitProcessRunner runner, bool tracked)
    {
        var repositoryPath = Path.Combine(Path.GetTempPath(), $"Codelaxy H1 {Guid.NewGuid():N}");

        Directory.CreateDirectory(repositoryPath);

        try
        {
            await RunGitAsync(runner, repositoryPath, "init", "-b", "main");

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, UnreadableName), "content\n");

            var padding = new string('p', PaddingNameLength);

            for (var index = 0; index < PaddingFileCount; index++)
            {
                var name = $"f{index.ToString("D5", CultureInfo.InvariantCulture)}-{padding}.txt";

                await File.WriteAllTextAsync(Path.Combine(repositoryPath, name), "content\n");
            }

            if (tracked)
            {
                await RunGitAsync(runner, repositoryPath, "add", "-A");
            }
            else
            {
                await File.WriteAllTextAsync(
                    Path.Combine(repositoryPath, "anchor.txt"),
                    "anchor\n"
                );
                await RunGitAsync(runner, repositoryPath, "add", "--", "anchor.txt");
            }

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "H1 fixture"
            );

            return repositoryPath;
        }
        catch
        {
            DeleteDirectory(repositoryPath);
            throw;
        }
    }

    private static async Task RunGitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments
    )
    {
        var result = await runner.RunAsync(repositoryPath, arguments);

        Assert.True(result.Succeeded, $"git {string.Join(' ', arguments)}: {result.StandardError}");
    }

    private static void DeleteDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
        {
            File.SetAttributes(file, FileAttributes.Normal);

            if (!OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(file, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
        }

        foreach (
            var directory in Directory.EnumerateDirectories(path, "*", SearchOption.AllDirectories)
        )
        {
            File.SetAttributes(directory, FileAttributes.Normal);
        }

        File.SetAttributes(path, FileAttributes.Normal);
        Directory.Delete(path, recursive: true);
    }

    // Makes one file unreadable for Git and proves that it really is, so that a test can never
    // pass because the obstruction silently did not work (for example when running as root).
    private sealed class Obstruction : IDisposable
    {
        private readonly string _path;
        private readonly FileStream? _lock;

        private Obstruction(string path, FileStream? fileLock)
        {
            _path = path;
            _lock = fileLock;
        }

        public static Obstruction Create(string path)
        {
            Obstruction obstruction;

            if (OperatingSystem.IsWindows())
            {
                obstruction = new Obstruction(
                    path,
                    new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None)
                );
            }
            else
            {
                File.SetUnixFileMode(path, UnixFileMode.None);
                obstruction = new Obstruction(path, null);
            }

            try
            {
                using var probe = File.OpenRead(path);
            }
            catch (Exception exception)
                when (exception is IOException or UnauthorizedAccessException)
            {
                return obstruction;
            }

            obstruction.Dispose();

            throw new Xunit.Sdk.XunitException(
                "ENVIRONMENT: the file is still readable after it was made unreadable "
                    + "(running as root, or the file system ignores permissions). "
                    + "This is not a result for H1."
            );
        }

        public void Dispose()
        {
            _lock?.Dispose();

            if (!OperatingSystem.IsWindows() && File.Exists(_path))
            {
                File.SetUnixFileMode(_path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
        }
    }
}
