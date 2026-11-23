using System.Runtime.Versioning;
using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// F10: a path enumerated by `git ls-files --others` can disappear before
// GitSnapshotBuilder inspects it in the working tree. A test-owned Git proxy
// (tests/Codelaxy.F10GitProxy) captures Git's real -z output, deletes the
// enumerated file and only then hands the original output to the builder.
// Expected contract: no exception escapes BuildAsync, no snapshot is produced
// and the diagnostic reports a repository change during capture.
//
// What this test proves per platform (observed before the fix):
// - Linux: an unhandled FileNotFoundException escaped BuildAsync
//   (GetUntrackedRegularFileMode -> File.GetUnixFileMode). This is a real
//   fail-closed violation.
// - Windows: no exception and no snapshot were produced; the result was already
//   fail-closed. Only the diagnostic differed ("Unable to hash untracked files: ...")
//   because the vanished file surfaced later as a `git hash-object` failure.
//   On Windows this test therefore pins the diagnostic classification only.
[Collection("GitWrapperIsolation")]
public sealed class GitSnapshotVanishedUntrackedF10Tests
{
    [Theory]
    [InlineData("victim.txt")]
    [InlineData("name with spaces.txt")]
    [InlineData("příliš-žluťoučký-kůň.txt")]
    // Whole untracked directory vanishes: reaches the DirectoryNotFoundException branch.
    [InlineData("sub/victim.txt")]
    public async Task BuildAsync_ReturnsDiagnosticWhenEnumeratedUntrackedFileVanished(
        string victimName
    )
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var proxyDirectory = Path.Combine(root, "proxy");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            var victimPath = Path.Combine(repositoryPath, victimName);
            Directory.CreateDirectory(Path.GetDirectoryName(victimPath)!);
            await File.WriteAllTextAsync(victimPath, "F10 payload\n");

            // Positive control: the same repository is observable before the race.
            var baseline = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);
            Assert.True(baseline.Succeeded, baseline.Diagnostic);
            Assert.NotNull(baseline.Snapshot);

            var proxyExecutable = await DeployProxyAsync(realGit, proxyDirectory, victimName);
            var builder = new GitSnapshotBuilder(new GitProcessRunner(proxyExecutable));

            GitSnapshotBuildResult? observed = null;
            var exception = await Record.ExceptionAsync(async () =>
            {
                observed = await builder.BuildAsync(repositoryPath);
            });

            // Prove the trigger fired on the intended Git call with the real output.
            var hitPath = Path.Combine(proxyDirectory, "f10-hit.bin");
            Assert.True(File.Exists(hitPath), "The proxy did not intercept the enumeration.");
            Assert.Equal(
                victimName + "\0",
                Encoding.UTF8.GetString(await File.ReadAllBytesAsync(hitPath))
            );
            Assert.False(File.Exists(victimPath), "F10 victim file must be gone.");

            Assert.Null(exception);
            Assert.NotNull(observed);
            Assert.False(observed.Succeeded);
            Assert.Null(observed.Snapshot);
            Assert.Contains(
                "changed during snapshot capture",
                observed.Diagnostic,
                StringComparison.OrdinalIgnoreCase
            );
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    [Fact]
    public async Task Proxy_RefusesToTouchForeignRepository()
    {
        const string victimName = "victim.txt";
        var root = CreateTestRoot();
        var proxyDirectory = Path.Combine(root, "proxy");
        var foreignRepository = Path.Combine(root, "foreign-repository");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, foreignRepository);

            var foreignVictim = Path.Combine(foreignRepository, victimName);
            await File.WriteAllTextAsync(foreignVictim, "must survive\n");

            var proxyExecutable = await DeployProxyAsync(realGit, proxyDirectory, victimName);

            var result = await new GitProcessRunner(proxyExecutable).RunReadOnlyAsync(
                foreignRepository,
                [
                    "-C",
                    foreignRepository,
                    "ls-files",
                    "--others",
                    "--exclude-per-directory=.gitignore",
                    "-z",
                ],
                TimeSpan.FromMinutes(2),
                CancellationToken.None
            );

            Assert.False(result.Succeeded);
            Assert.Contains(
                "F10 repository mismatch",
                result.StandardError,
                StringComparison.Ordinal
            );
            Assert.True(File.Exists(foreignVictim), "Proxy must not delete foreign files.");
            Assert.False(File.Exists(Path.Combine(proxyDirectory, "f10-hit.bin")));
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    [Theory]
    [InlineData("../victim.txt")]
    [InlineData("sub/../victim.txt")]
    [InlineData("./victim.txt")]
    [InlineData("/victim.txt")]
    [InlineData("a/b/victim.txt")]
    [InlineData("sub\\victim.txt")]
    [InlineData("sub/")]
    public async Task Proxy_RejectsVictimOutsidePlainRepositoryPath(string victimName)
    {
        var root = CreateTestRoot();
        var proxyDirectory = Path.Combine(root, "proxy");
        var repositoryPath = Path.Combine(root, "repository");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            var proxyExecutable = await DeployProxyAsync(realGit, proxyDirectory, victimName);

            var result = await new GitProcessRunner(proxyExecutable).RunReadOnlyAsync(
                repositoryPath,
                ["--version"],
                TimeSpan.FromMinutes(2),
                CancellationToken.None
            );

            Assert.False(result.Succeeded);
            Assert.Contains(
                "Invalid F10 Git proxy configuration",
                result.StandardError,
                StringComparison.Ordinal
            );
            Assert.False(File.Exists(Path.Combine(proxyDirectory, "f10-hit.bin")));
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    // CR-003, window W1: a tracked path vanishes after `ls-files --stage` listed it
    // and before the working tree is observed. Both observations of BuildAsync then
    // see it missing, so the snapshot is valid: it must equal a clean BuildAsync of
    // the tree after the race, and only the working-tree fingerprint may differ from
    // the state before the race.
    [Theory]
    [InlineData("victim.txt", false)]
    [InlineData("sub/victim.txt", false)]
    // Symbolic links are created only on Linux; on other systems the case is skipped.
    [LinuxOnlyInlineData("link.txt", true)]
    public async Task BuildAsync_ReturnsSnapshotOfMissingPathWhenTrackedPathVanishedBeforeObservation(
        string victimName,
        bool symlink
    )
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var proxyDirectory = Path.Combine(root, "proxy");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            var victimPath = await CreateTrackedVictimAsync(
                realGit,
                repositoryPath,
                victimName,
                symlink
            );

            var before = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);
            Assert.True(before.Succeeded, before.Diagnostic);

            await DeployProxyAsync(realGit, proxyDirectory, victimName);
            var proxyExecutable = await ArmProxyModeAsync(proxyDirectory, "index");
            var builder = new GitSnapshotBuilder(new GitProcessRunner(proxyExecutable));

            GitSnapshotBuildResult? observed = null;
            var exception = await Record.ExceptionAsync(async () =>
            {
                observed = await builder.BuildAsync(repositoryPath);
            });

            // Prove the trigger fired on the index listing that named the victim.
            var hitPath = Path.Combine(proxyDirectory, "f10-hit.bin");
            Assert.True(File.Exists(hitPath), "The proxy did not intercept the index listing.");
            Assert.Contains(
                "\t" + victimName + "\0",
                Encoding.UTF8.GetString(await File.ReadAllBytesAsync(hitPath)),
                StringComparison.Ordinal
            );
            Assert.True(IsEntryGone(victimPath), "CR-003 victim must be gone.");

            Assert.Null(exception);
            Assert.NotNull(observed);
            Assert.True(observed.Succeeded, observed.Diagnostic);

            var after = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);
            Assert.True(after.Succeeded, after.Diagnostic);

            var raced = observed.Snapshot!;
            var clean = after.Snapshot!;
            var initial = before.Snapshot!;

            Assert.Equal(clean.HeadFingerprint, raced.HeadFingerprint);
            Assert.Equal(clean.IndexFingerprint, raced.IndexFingerprint);
            Assert.Equal(clean.WorkingTreeFingerprint, raced.WorkingTreeFingerprint);
            Assert.Equal(clean.StagedFingerprint, raced.StagedFingerprint);

            Assert.NotEqual(initial.WorkingTreeFingerprint, raced.WorkingTreeFingerprint);
            Assert.Equal(initial.HeadFingerprint, raced.HeadFingerprint);
            Assert.Equal(initial.IndexFingerprint, raced.IndexFingerprint);
            Assert.Equal(initial.StagedFingerprint, raced.StagedFingerprint);
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    // CR-003, windows W2 and W3: a tracked path vanishes after it was observed and
    // before its content is read (`hash-object --stdin-paths` for a regular file,
    // FileInfo.LinkTarget for a symbolic link). No snapshot may be produced.
    // GitProcessRunner does not set LANG, LC_* or LANGUAGE, so Git's own message can
    // be localized; only the builder's prefix and the path are pinned.
    [Theory]
    [InlineData("victim.txt", false, "Unable to hash tracked working-tree files: ")]
    [InlineData("sub/victim.txt", false, "Unable to hash tracked working-tree files: ")]
    // Symbolic links are created only on Linux; on other systems the case is skipped.
    [LinuxOnlyInlineData("link.txt", true, "Unable to read tracked symbolic link 'link.txt'.")]
    public async Task BuildAsync_ReturnsDiagnosticWhenTrackedPathVanishedAfterObservation(
        string victimName,
        bool symlink,
        string expectedDiagnosticStart
    )
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var proxyDirectory = Path.Combine(root, "proxy");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            var victimPath = await CreateTrackedVictimAsync(
                realGit,
                repositoryPath,
                victimName,
                symlink
            );

            var before = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);
            Assert.True(before.Succeeded, before.Diagnostic);

            await DeployProxyAsync(realGit, proxyDirectory, victimName);
            var proxyExecutable = await ArmProxyModeAsync(proxyDirectory, "hash");
            var builder = new GitSnapshotBuilder(new GitProcessRunner(proxyExecutable));

            GitSnapshotBuildResult? observed = null;
            var exception = await Record.ExceptionAsync(async () =>
            {
                observed = await builder.BuildAsync(repositoryPath);
            });

            // Prove the trigger fired on the hash request: a regular victim is among
            // the requested paths, a symbolic link is not (only keep.txt is hashed).
            var hitPath = Path.Combine(proxyDirectory, "f10-hit.bin");
            Assert.True(File.Exists(hitPath), "The proxy did not intercept hash-object.");
            var requestedPaths = Encoding.UTF8.GetString(await File.ReadAllBytesAsync(hitPath));
            Assert.Contains("\"keep.txt\"\n", requestedPaths, StringComparison.Ordinal);
            Assert.Equal(
                !symlink,
                requestedPaths.Contains("\"" + victimName + "\"\n", StringComparison.Ordinal)
            );
            Assert.True(IsEntryGone(victimPath), "CR-003 victim must be gone.");

            Assert.Null(exception);
            Assert.NotNull(observed);
            Assert.False(observed.Succeeded);
            Assert.Null(observed.Snapshot);
            Assert.StartsWith(
                expectedDiagnosticStart,
                observed.Diagnostic,
                StringComparison.Ordinal
            );
            Assert.Contains(victimName, observed.Diagnostic, StringComparison.Ordinal);
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    // CR-003 step 3, finding F-2: on Windows `git ls-files --others` lists a file
    // named NUL, and File.GetAttributes for that path throws IOException ('\\.\NUL'),
    // which is neither FileNotFoundException nor DirectoryNotFoundException.
    // BuildAsync must fail closed with a diagnostic instead of throwing.
    [WindowsOnlyFact]
    public async Task BuildAsync_ReturnsDiagnosticWhenUntrackedPathCannotBeObservedOnWindows()
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var devicePath = @"\\?\" + Path.Combine(repositoryPath, "NUL");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            // The extended-length prefix creates a real file instead of opening the device.
            await File.WriteAllTextAsync(devicePath, "F-2 payload\n");

            // Positive control: Git itself lists the path the builder will inspect.
            var listed = await realGit.RunReadOnlyAsync(
                repositoryPath,
                [
                    "-C",
                    repositoryPath,
                    "ls-files",
                    "--others",
                    "--exclude-per-directory=.gitignore",
                    "-z",
                ],
                TimeSpan.FromMinutes(2),
                CancellationToken.None
            );
            Assert.True(listed.Succeeded, listed.StandardError);
            Assert.Equal("NUL\0", listed.StandardOutput);

            GitSnapshotBuildResult? observed = null;
            var exception = await Record.ExceptionAsync(async () =>
            {
                observed = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);
            });

            Assert.Null(exception);
            Assert.NotNull(observed);
            Assert.False(observed.Succeeded);
            Assert.Null(observed.Snapshot);
            Assert.StartsWith(
                "Unable to observe untracked path 'NUL': ",
                observed.Diagnostic,
                StringComparison.Ordinal
            );
        }
        finally
        {
            if (File.Exists(devicePath))
            {
                File.Delete(devicePath);
            }

            DeleteTestDirectory(root);
        }
    }

    // CR-003 audit G-1: F-2 also exists on Linux. In a directory that can be listed
    // but not searched (r--r--r--), `git ls-files --others` still lists the untracked
    // file, but File.GetUnixFileMode throws UnauthorizedAccessException, which
    // escaped BuildAsync before the fix. A privileged process bypasses the
    // permissions, so the attribute skips the test visibly for it.
    [LinuxUnprivilegedFact]
    [SupportedOSPlatform("linux")]
    public async Task BuildAsync_ReturnsDiagnosticWhenUntrackedPathCannotBeObservedOnLinux()
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var directoryPath = Path.Combine(repositoryPath, "sub");
        var entryPath = Path.Combine(directoryPath, "entry.txt");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            Directory.CreateDirectory(directoryPath);
            await File.WriteAllTextAsync(entryPath, "G-1 payload\n");

            // Listable but not searchable: names can be read, entries cannot be reached.
            File.SetUnixFileMode(
                directoryPath,
                UnixFileMode.UserRead | UnixFileMode.GroupRead | UnixFileMode.OtherRead
            );

            // Positive control: Git lists the path, and reading its mode is refused.
            var listed = await realGit.RunReadOnlyAsync(
                repositoryPath,
                [
                    "-C",
                    repositoryPath,
                    "ls-files",
                    "--others",
                    "--exclude-per-directory=.gitignore",
                    "-z",
                ],
                TimeSpan.FromMinutes(2),
                CancellationToken.None
            );
            Assert.True(listed.Succeeded, listed.StandardError);
            Assert.Equal("sub/entry.txt\0", listed.StandardOutput);

            var modeException = Record.Exception(() => File.GetUnixFileMode(entryPath));
            Assert.True(
                modeException is UnauthorizedAccessException,
                "Precondition failed: this test needs an unprivileged user for whom reading "
                    + "a file mode in a r--r--r-- directory is refused; got "
                    + (modeException?.GetType().FullName ?? "no exception")
                    + "."
            );

            GitSnapshotBuildResult? observed = null;
            var exception = await Record.ExceptionAsync(async () =>
            {
                observed = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);
            });

            Assert.Null(exception);
            Assert.NotNull(observed);
            Assert.False(observed.Succeeded);
            Assert.Null(observed.Snapshot);
            Assert.StartsWith(
                "Unable to observe untracked path 'sub/entry.txt': ",
                observed.Diagnostic,
                StringComparison.Ordinal
            );
        }
        finally
        {
            // Restore the permissions first, or the directory cannot be deleted.
            if (Directory.Exists(directoryPath))
            {
                File.SetUnixFileMode(
                    directoryPath,
                    UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
                );
            }

            DeleteTestDirectory(root);
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData("INDEX")]
    [InlineData("hash ")]
    [InlineData("stage")]
    public async Task Proxy_RejectsUnknownMode(string mode)
    {
        var root = CreateTestRoot();
        var proxyDirectory = Path.Combine(root, "proxy");
        var repositoryPath = Path.Combine(root, "repository");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            await DeployProxyAsync(realGit, proxyDirectory, "victim.txt");
            var proxyExecutable = await ArmProxyModeAsync(proxyDirectory, mode);

            var result = await new GitProcessRunner(proxyExecutable).RunReadOnlyAsync(
                repositoryPath,
                ["--version"],
                TimeSpan.FromMinutes(2),
                CancellationToken.None
            );

            Assert.False(result.Succeeded);
            Assert.Contains(
                "Invalid F10 Git proxy configuration",
                result.StandardError,
                StringComparison.Ordinal
            );
            Assert.False(File.Exists(Path.Combine(proxyDirectory, "f10-hit.bin")));
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    [Theory]
    [InlineData("index")]
    [InlineData("hash")]
    public async Task Proxy_RefusesToTouchForeignRepositoryInTrackedModes(string mode)
    {
        const string victimName = "victim.txt";
        var root = CreateTestRoot();
        var proxyDirectory = Path.Combine(root, "proxy");
        var foreignRepository = Path.Combine(root, "foreign-repository");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, foreignRepository);

            var foreignVictim = await CreateTrackedVictimAsync(
                realGit,
                foreignRepository,
                victimName,
                symlink: false
            );

            await DeployProxyAsync(realGit, proxyDirectory, victimName);
            var proxyExecutable = await ArmProxyModeAsync(proxyDirectory, mode);
            var proxy = new GitProcessRunner(proxyExecutable);

            var result =
                mode == "index"
                    ? await proxy.RunReadOnlyAsync(
                        foreignRepository,
                        ["-C", foreignRepository, "ls-files", "--stage", "-t", "-z"],
                        TimeSpan.FromMinutes(2),
                        CancellationToken.None
                    )
                    : await proxy.RunReadOnlyAsync(
                        foreignRepository,
                        ["-C", foreignRepository, "hash-object", "--no-filters", "--stdin-paths"],
                        TimeSpan.FromMinutes(2),
                        Encoding.UTF8.GetBytes("\"" + victimName + "\"\n"),
                        CancellationToken.None
                    );

            Assert.False(result.Succeeded);
            Assert.Contains(
                "F10 repository mismatch",
                result.StandardError,
                StringComparison.Ordinal
            );
            Assert.True(File.Exists(foreignVictim), "Proxy must not delete foreign files.");
            Assert.False(File.Exists(Path.Combine(proxyDirectory, "f10-hit.bin")));
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    // Commits "keep.txt" (a regular companion, so `hash-object --stdin-paths` always
    // runs) and the victim: a regular file, a file in its own directory, or a
    // symbolic link to keep.txt. Returns the victim's full path.
    private static async Task<string> CreateTrackedVictimAsync(
        GitProcessRunner git,
        string repositoryPath,
        string victimName,
        bool symlink
    )
    {
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "keep.txt"), "keep\n");

        var victimPath = Path.Combine(repositoryPath, victimName);
        Directory.CreateDirectory(Path.GetDirectoryName(victimPath)!);

        if (symlink)
        {
            File.CreateSymbolicLink(victimPath, "keep.txt");
        }
        else
        {
            await File.WriteAllTextAsync(victimPath, "CR-003 payload\n");
        }

        var add = await git.RunAsync(repositoryPath, ["add", "--", "keep.txt", victimName]);
        Assert.True(add.Succeeded, add.StandardError);

        var commit = await git.RunAsync(
            repositoryPath,
            [
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "-m",
                "CR-003 tracked victim",
            ]
        );
        Assert.True(commit.Succeeded, commit.StandardError);

        return victimPath;
    }

    // Appends the CR-003 trigger mode as line 3 of a configuration written by DeployProxyAsync.
    private static async Task<string> ArmProxyModeAsync(string proxyDirectory, string mode)
    {
        await File.AppendAllLinesAsync(Path.Combine(proxyDirectory, "f10-git-proxy.conf"), [mode]);

        return Path.Combine(
            proxyDirectory,
            OperatingSystem.IsWindows() ? "Codelaxy.F10GitProxy.exe" : "Codelaxy.F10GitProxy"
        );
    }

    // True when no directory entry of that name exists, including a dangling symbolic link.
    private static bool IsEntryGone(string path)
    {
        var parent = Path.GetDirectoryName(path)!;
        var name = Path.GetFileName(path);

        return !Directory.Exists(parent)
            || !Directory
                .EnumerateFileSystemEntries(parent)
                .Any(entry =>
                    string.Equals(Path.GetFileName(entry), name, StringComparison.Ordinal)
                );
    }

    private static string CreateTestRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), $"codelaxy-f10-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        return root;
    }

    private static async Task InitializeRepositoryAsync(GitProcessRunner git, string path)
    {
        Directory.CreateDirectory(path);
        await GoldenGitFixture.InitializeSha1Async(git, path);

        var commit = await git.RunAsync(
            path,
            [
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "F10 baseline",
            ]
        );
        Assert.True(commit.Succeeded, commit.StandardError);
    }

    // Copies the proxy build output to a test-owned directory and writes the
    // configuration ONLY there, so no shared build output is ever armed.
    private static async Task<string> DeployProxyAsync(
        GitProcessRunner realGit,
        string proxyDirectory,
        string victimName
    )
    {
        var gitStartInfo = realGit.CreateProcessStartInfo(
            Path.GetTempPath(),
            ["--version"],
            readOnly: true
        );
        Assert.True(Path.IsPathFullyQualified(gitStartInfo.FileName));
        Assert.True(File.Exists(gitStartInfo.FileName));

        var outputDirectory = GetProxyOutputDirectory();
        Assert.True(Directory.Exists(outputDirectory), $"Proxy output missing: {outputDirectory}");

        Directory.CreateDirectory(proxyDirectory);

        foreach (var source in Directory.EnumerateFiles(outputDirectory, "Codelaxy.F10GitProxy*"))
        {
            File.Copy(source, Path.Combine(proxyDirectory, Path.GetFileName(source)));
        }

        var executable = Path.Combine(
            proxyDirectory,
            OperatingSystem.IsWindows() ? "Codelaxy.F10GitProxy.exe" : "Codelaxy.F10GitProxy"
        );
        Assert.True(File.Exists(executable), $"Proxy apphost missing: {executable}");

        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(
                executable,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
            );
        }

        await File.WriteAllLinesAsync(
            Path.Combine(proxyDirectory, "f10-git-proxy.conf"),
            [gitStartInfo.FileName, victimName]
        );

        return executable;
    }

    // Same layout rule as GitProcessRunnerTests.GetProcessTestHelperPath:
    // tests/<project>/bin/<host>/<configuration>/<tfm>.
    private static string GetProxyOutputDirectory()
    {
        var tfm = new DirectoryInfo(AppContext.BaseDirectory);
        var configuration = tfm.Parent!;
        var host = configuration.Parent!;
        var testsDirectory = host.Parent!.Parent!.Parent!;

        return Path.Combine(
            testsDirectory.FullName,
            "Codelaxy.F10GitProxy",
            "bin",
            host.Name,
            configuration.Name,
            tfm.Name
        );
    }

    private static void DeleteTestDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            return;
        }

        // Git object files are read-only on Windows.
        foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
        {
            File.SetAttributes(file, FileAttributes.Normal);
        }

        Directory.Delete(path, recursive: true);
    }
}
