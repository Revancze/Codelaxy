using System.Diagnostics;
using System.Runtime.InteropServices;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// G2: Linux file names that are not valid UTF-8 decode to U+FFFD in .NET, so
// distinct names (and symlink targets) can collapse into one string.

// T1 verification obligations — Linux native test-fixture cleanup.
//
// T1-C1: Cleanup must not invoke external rm from PATH.
// Evidence: poisoned-PATH probe with the invalid UTF-8 test.
//
// T1-C2: Cleanup must preserve raw filesystem name bytes.
// Test: LinuxNativeCleanup_RemovesInvalidUtf8Directory.
//
// T1-C3: Cleanup must not follow symlinks outside its root.
// Test: LinuxNativeCleanup_DoesNotFollowDirectorySymlink.
//
// T1-C4: A missing root is a no-op; remove failures must propagate.
// Tests: LinuxNativeCleanup_MissingRootIsNoOp
//        LinuxNativeCleanup_PropagatesRemoveFailure.
//
// Scope: isolated test directories, not hostile concurrent trees.

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

    [Fact]
    public async Task BuildAsync_DistinguishesUntrackedNameWithLeadingByteOrderMark()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await InitializeRepositoryAsync(runner, repositoryPath);

            // Two different files: "x" and "\uFEFFx".
            var trackedPath = Path.Combine(repositoryPath, "x");
            var untrackedPath = Path.Combine(repositoryPath, "\uFEFFx");

            await File.WriteAllTextAsync(trackedPath, "tracked\n");

            await RunGitAsync(runner, repositoryPath, "add", "x");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "add tracked x"
            );

            await File.WriteAllTextAsync(untrackedPath, "one\n");

            var builder = new GitSnapshotBuilder(runner);

            var first = await builder.BuildAsync(repositoryPath);

            Assert.True(first.Succeeded, first.Diagnostic);
            Assert.NotNull(first.Snapshot);

            await File.WriteAllTextAsync(untrackedPath, "two\n");

            var second = await builder.BuildAsync(repositoryPath);

            Assert.True(second.Succeeded, second.Diagnostic);
            Assert.NotNull(second.Snapshot);

            Assert.NotEqual(
                first.Snapshot.WorkingTreeFingerprint,
                second.Snapshot.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectoryNatively(repositoryPath);
        }
    }

    [Fact]
    public async Task BuildAsync_RejectsUntrackedNameStartingWithUtf16ByteOrderMarkOnLinux()
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

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "a"), "tracked\n");

            await RunGitAsync(runner, repositoryPath, "add", "a");

            await RunGitAsync(
                runner,
                repositoryPath,
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "add tracked a"
            );

            // Raw filename bytes: FF FE 61
            RunShell(repositoryPath, "printf 'one\\n' > \"$(printf '\\377\\376a')\"");

            Assert.Contains("ff fe 61 00", ListRawNameBytes(repositoryPath));

            var result = await new GitSnapshotBuilder(runner).BuildAsync(repositoryPath);

            AssertRefused(result);
        }
        finally
        {
            DeleteDirectoryNatively(repositoryPath);
        }
    }

    [Fact]
    public void DeleteDirectoryNatively_DoesNotFollowWindowsJunction()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var sandbox = Path.Combine(Path.GetTempPath(), $"Codelaxy G2 Junction {Guid.NewGuid():N}");
        var repository = Path.Combine(sandbox, "repository");
        var outside = Path.Combine(sandbox, "outside");
        var junction = Path.Combine(repository, "junction");
        var sentinel = Path.Combine(outside, "sentinel.txt");

        Directory.CreateDirectory(repository);
        Directory.CreateDirectory(outside);
        File.WriteAllText(sentinel, "external");
        File.SetAttributes(sentinel, File.GetAttributes(sentinel) | FileAttributes.ReadOnly);

        try
        {
            using var process = Process.Start(
                new ProcessStartInfo("cmd.exe", ["/c", "mklink", "/J", junction, outside])
                {
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                }
            )!;

            process.WaitForExit();
            Assert.Equal(0, process.ExitCode);
            Assert.NotNull(new DirectoryInfo(junction).LinkTarget);

            DeleteDirectoryNatively(repository);

            Assert.False(Directory.Exists(repository));
            Assert.True(File.Exists(sentinel), "Cleanup followed an external junction");
            Assert.True(
                (File.GetAttributes(sentinel) & FileAttributes.ReadOnly) != FileAttributes.None
            );
        }
        finally
        {
            if (Directory.Exists(junction))
            {
                Directory.Delete(junction);
            }

            if (File.Exists(sentinel))
            {
                File.SetAttributes(sentinel, FileAttributes.Normal);
            }

            if (Directory.Exists(sandbox))
            {
                Directory.Delete(sandbox, recursive: true);
            }
        }
    }

    [Fact]
    public void LinuxNativeCleanup_DoesNotFollowDirectorySymlink()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var sandbox = Path.Combine(Path.GetTempPath(), $"codelaxy-cleanup-{Guid.NewGuid():N}");

        var root = Path.Combine(sandbox, "root");
        var outside = Path.Combine(sandbox, "outside");
        var sentinel = Path.Combine(outside, "sentinel.txt");
        var link = Path.Combine(root, "escape");

        Directory.CreateDirectory(root);
        Directory.CreateDirectory(outside);

        try
        {
            File.WriteAllText(sentinel, "KEEP");
            Directory.CreateSymbolicLink(link, outside);

            Assert.True(File.Exists(sentinel));

            LinuxNativeDirectoryCleanup.Delete(root);

            Assert.False(Path.Exists(root));
            Assert.True(Directory.Exists(outside));
            Assert.Equal("KEEP", File.ReadAllText(sentinel));
        }
        finally
        {
            if (Directory.Exists(root))
            {
                LinuxNativeDirectoryCleanup.Delete(root);
            }

            if (Directory.Exists(outside))
            {
                Directory.Delete(outside, recursive: true);
            }

            if (Directory.Exists(sandbox))
            {
                Directory.Delete(sandbox);
            }
        }
    }

    [Fact]
    public void LinuxNativeCleanup_MissingRootIsNoOp()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var sandbox = Path.Combine(Path.GetTempPath(), $"codelaxy-missing-root-{Guid.NewGuid():N}");

        Directory.CreateDirectory(sandbox);

        try
        {
            var missingRoot = Path.Combine(sandbox, "missing");

            Assert.False(Path.Exists(missingRoot));

            LinuxNativeDirectoryCleanup.Delete(missingRoot);

            Assert.False(Path.Exists(missingRoot));
        }
        finally
        {
            Directory.Delete(sandbox);
        }
    }

    [Fact]
    public void LinuxNativeCleanup_RemovesInvalidUtf8Directory()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var root = Path.Combine(Path.GetTempPath(), $"codelaxy-native-cleanup-{Guid.NewGuid():N}");

        Directory.CreateDirectory(root);

        try
        {
            var prefix = System.Text.Encoding.UTF8.GetBytes(Path.Combine(root, "invalid-"));

            var bytes = new byte[prefix.Length + 2];
            prefix.CopyTo(bytes, 0);

            bytes[^2] = 0xFF;
            bytes[^1] = 0;

            var nativePath = Marshal.AllocHGlobal(bytes.Length);

            try
            {
                Marshal.Copy(bytes, 0, nativePath, bytes.Length);

                Assert.Equal(0, NativeMkdirForCleanupTest(nativePath, 448));
            }
            finally
            {
                Marshal.FreeHGlobal(nativePath);
            }

            LinuxNativeDirectoryCleanup.Delete(root);

            Assert.False(Directory.Exists(root));
        }
        finally
        {
            if (Directory.Exists(root))
            {
                LinuxNativeDirectoryCleanup.Delete(root);
            }
        }
    }

    [Fact]
    public void LinuxNativeCleanup_PropagatesRemoveFailure()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var root = Path.Combine(Path.GetTempPath(), $"codelaxy-remove-failure-{Guid.NewGuid():N}");

        Directory.CreateDirectory(root);

        try
        {
            var exception = Assert.Throws<IOException>(() =>
                LinuxNativeDirectoryCleanup.Delete(
                    root,
                    _ =>
                    {
                        Marshal.SetLastPInvokeError(13);
                        return -1;
                    }
                )
            );

            Assert.Contains("errno 13", exception.Message, StringComparison.Ordinal);

            Assert.True(Directory.Exists(root));
        }
        finally
        {
            LinuxNativeDirectoryCleanup.Delete(root);
        }
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport(
        "libc",
        EntryPoint = "mkdir",
        CallingConvention = CallingConvention.Cdecl,
        SetLastError = true
    )]
    private static extern int NativeMkdirForCleanupTest(nint path, int mode);

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
                UseShellExecute = false,
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

    // Remove Windows test fixtures without following junctions or symlinks.
    private static void DeleteWindowsDirectoryTree(string directory)
    {
        foreach (var entry in new DirectoryInfo(directory).EnumerateFileSystemInfos())
        {
            var attributes = entry.Attributes;
            var isDirectory = (attributes & FileAttributes.Directory) != FileAttributes.None;
            var isReparsePoint = (attributes & FileAttributes.ReparsePoint) != FileAttributes.None;

            if (isDirectory)
            {
                if (isReparsePoint)
                {
                    // Delete the link itself, never recurse into its target.
                    Directory.Delete(entry.FullName);
                }
                else
                {
                    DeleteWindowsDirectoryTree(entry.FullName);
                }
            }
            else
            {
                if (
                    !isReparsePoint
                    && (attributes & FileAttributes.ReadOnly) != FileAttributes.None
                )
                {
                    File.SetAttributes(entry.FullName, attributes & ~FileAttributes.ReadOnly);
                }

                File.Delete(entry.FullName);
            }
        }

        Directory.Delete(directory);
    }

    // .NET cannot delete a name it decodes to U+FFFD; remove the tree natively.

    private static void DeleteDirectoryNatively(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            DeleteWindowsDirectoryTree(path);
            return;
        }

        if (OperatingSystem.IsLinux())
        {
            LinuxNativeDirectoryCleanup.Delete(path);
            return;
        }

        // Preserve the original cleanup behavior on other platforms.
        using var process = Process.Start("rm", ["-rf", "--", path]);

        Assert.NotNull(process);
        process.WaitForExit();
        Assert.Equal(0, process.ExitCode);
    }
}
