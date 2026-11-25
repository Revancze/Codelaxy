using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// P1.2-CR-003, finding N-2: when Git cannot read a directory of the working tree,
// `git ls-files --others` only prints a warning on standard error and exits with 0.
// Its listing then either leaves the directory's content out, or contains it without
// the directory's .gitignore having been read. A snapshot built from that listing
// would not describe the tree, so any message on standard error of a successful
// enumeration must end in a failure without a snapshot. Git's own text is not
// pinned: GitProcessRunner does not set the language of Git.
public sealed partial class GitSnapshotVanishedUntrackedF10Tests
{
    private const string EnumerationDiagnostic = "Unable to enumerate untracked files: ";

    // Linux: "000" hides the directory completely; "444" (listable, not searchable)
    // still lists sub/entry.txt but Git cannot read sub/.gitignore. A privileged
    // process bypasses the permissions, so the attribute skips the test visibly for it.
    [LinuxUnprivilegedTheory]
    [InlineData("000", "other.txt\0")]
    [InlineData("444", "other.txt\0sub/entry.txt\0")]
    [SupportedOSPlatform("linux")]
    public async Task BuildAsync_ReturnsDiagnosticWhenGitWarnsAboutUnreadableDirectoryOnLinux(
        string directoryMode,
        string expectedListing
    )
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var directoryPath = Path.Combine(repositoryPath, "sub");

        try
        {
            var realGit = new GitProcessRunner();
            await CreateUnreadableDirectoryRepositoryAsync(realGit, repositoryPath);

            File.SetUnixFileMode(
                directoryPath,
                directoryMode == "000"
                    ? UnixFileMode.None
                    : UnixFileMode.UserRead | UnixFileMode.GroupRead | UnixFileMode.OtherRead
            );

            await AssertGitWarnsWithListingAsync(realGit, repositoryPath, expectedListing);
            await AssertEnumerationFailureAsync(realGit, repositoryPath);
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

    // Windows: the current user may not list the directory (a deny entry applies to
    // administrators as well).
    [WindowsOnlyFact]
    [SupportedOSPlatform("windows")]
    public async Task BuildAsync_ReturnsDiagnosticWhenGitCannotListDirectoryOnWindows()
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var directory = new DirectoryInfo(Path.Combine(repositoryPath, "sub"));
        var denyListing = new FileSystemAccessRule(
            WindowsIdentity.GetCurrent().User!,
            FileSystemRights.ListDirectory,
            AccessControlType.Deny
        );
        var denied = false;

        try
        {
            var realGit = new GitProcessRunner();
            await CreateUnreadableDirectoryRepositoryAsync(realGit, repositoryPath);

            var security = directory.GetAccessControl();
            security.AddAccessRule(denyListing);
            directory.SetAccessControl(security);
            denied = true;

            await AssertGitWarnsWithListingAsync(realGit, repositoryPath, "other.txt\0");
            await AssertEnumerationFailureAsync(realGit, repositoryPath);
        }
        finally
        {
            // Remove the deny entry first, or the directory cannot be deleted.
            if (denied)
            {
                var security = directory.GetAccessControl();
                security.RemoveAccessRule(denyListing);
                directory.SetAccessControl(security);
            }

            DeleteTestDirectory(root);
        }
    }

    // Windows: a path longer than Git accepts while core.longpaths is false. The value
    // is set in the test repository's own configuration, so the runner's system or
    // global configuration cannot change the state.
    [WindowsOnlyFact]
    public async Task BuildAsync_ReturnsDiagnosticWhenPathIsTooLongForGitOnWindows()
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");

        try
        {
            var realGit = new GitProcessRunner();
            await CreateUnreadableDirectoryRepositoryAsync(realGit, repositoryPath);

            var config = await realGit.RunAsync(
                repositoryPath,
                ["config", "core.longpaths", "false"]
            );
            Assert.True(config.Succeeded, config.StandardError);

            var longDirectory = @"\\?\" + repositoryPath;

            for (var index = 0; index < 6; ++index)
            {
                longDirectory += @"\" + new string((char)('a' + index), 50);
            }

            Directory.CreateDirectory(longDirectory);
            await File.WriteAllTextAsync(longDirectory + @"\long.txt", "N-2 payload\n");

            await AssertGitWarnsWithListingAsync(
                realGit,
                repositoryPath,
                "other.txt\0sub/entry.txt\0"
            );
            await AssertEnumerationFailureAsync(realGit, repositoryPath);
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    // Independent of the system: the proxy adds a line to standard error of a
    // successful and complete enumeration. The decision rests on standard error, not
    // on a missing entry.
    [Fact]
    public async Task BuildAsync_ReturnsDiagnosticWhenUntrackedEnumerationWritesToStandardError()
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var proxyDirectory = Path.Combine(root, "proxy");

        try
        {
            var realGit = new GitProcessRunner();
            await CreateUnreadableDirectoryRepositoryAsync(realGit, repositoryPath);

            await DeployProxyAsync(realGit, proxyDirectory, "sub/entry.txt");
            var proxyExecutable = await ArmProxyModeAsync(proxyDirectory, "stderr");

            await AssertEnumerationFailureAsync(
                new GitProcessRunner(proxyExecutable),
                repositoryPath
            );

            // Positive control: the proxy acted on a complete listing.
            var hitPath = Path.Combine(proxyDirectory, "f10-hit.bin");
            Assert.True(File.Exists(hitPath), "The proxy did not intercept the enumeration.");
            Assert.Equal(
                "other.txt\0sub/entry.txt\0",
                Encoding.UTF8.GetString(await File.ReadAllBytesAsync(hitPath))
            );
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    [Theory]
    [InlineData("stderr ")]
    [InlineData("STDERR")]
    [InlineData("deny-traverse ")]
    [InlineData("deny_traverse")]
    public async Task Proxy_RejectsMisspelledN2Mode(string mode)
    {
        await AssertProxyRejectsConfigurationAsync("sub/entry.txt", mode);
    }

    [Fact]
    public async Task Proxy_RejectsDenyTraverseVictimWithoutDirectory()
    {
        await AssertProxyRejectsConfigurationAsync("entry.txt", "deny-traverse");
    }

    [Theory]
    [InlineData("stderr")]
    [InlineData("deny-traverse")]
    public async Task Proxy_RefusesToTouchForeignRepositoryInUntrackedEnumerationModes(string mode)
    {
        var root = CreateTestRoot();
        var proxyDirectory = Path.Combine(root, "proxy");
        var foreignRepository = Path.Combine(root, "foreign-repository");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, foreignRepository);

            var foreignVictim = Path.Combine(foreignRepository, "sub", "entry.txt");
            Directory.CreateDirectory(Path.GetDirectoryName(foreignVictim)!);
            await File.WriteAllTextAsync(foreignVictim, "must stay reachable\n");

            await DeployProxyAsync(realGit, proxyDirectory, "sub/entry.txt");
            var proxyExecutable = await ArmProxyModeAsync(proxyDirectory, mode);

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
            Assert.Equal("must stay reachable\n", await File.ReadAllTextAsync(foreignVictim));
            Assert.False(File.Exists(Path.Combine(proxyDirectory, "f10-hit.bin")));
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    // A committed keep.txt, an untracked readable other.txt at the top level and an
    // untracked sub/entry.txt in the directory that the test makes unreadable.
    private static async Task CreateUnreadableDirectoryRepositoryAsync(
        GitProcessRunner git,
        string repositoryPath
    )
    {
        await InitializeRepositoryAsync(git, repositoryPath);
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "other.txt"), "other\n");

        var directoryPath = Path.Combine(repositoryPath, "sub");
        Directory.CreateDirectory(directoryPath);
        await File.WriteAllTextAsync(Path.Combine(directoryPath, "entry.txt"), "entry\n");
    }

    // Positive control: Git exits with 0, warns on standard error and still lists the
    // readable entries, so the test cannot pass on an empty listing alone.
    private static async Task AssertGitWarnsWithListingAsync(
        GitProcessRunner git,
        string repositoryPath,
        string expectedListing
    )
    {
        var listed = await git.RunReadOnlyAsync(
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

        Assert.True(
            listed.Succeeded,
            "Precondition failed: git ls-files --others must exit with 0: " + listed.StandardError
        );
        Assert.True(
            listed.StandardError.Trim().Length > 0,
            "Precondition failed: the state could not be built here, Git did not warn."
        );
        Assert.Equal(expectedListing, listed.StandardOutput);
    }

    private static async Task AssertEnumerationFailureAsync(
        GitProcessRunner git,
        string repositoryPath
    )
    {
        GitSnapshotBuildResult? observed = null;
        var exception = await Record.ExceptionAsync(async () =>
        {
            observed = await new GitSnapshotBuilder(git).BuildAsync(repositoryPath);
        });

        Assert.Null(exception);
        Assert.NotNull(observed);
        Assert.False(observed.Succeeded);
        Assert.Null(observed.Snapshot);
        Assert.StartsWith(EnumerationDiagnostic, observed.Diagnostic, StringComparison.Ordinal);
    }

    private static async Task AssertProxyRejectsConfigurationAsync(string victim, string mode)
    {
        var root = CreateTestRoot();
        var proxyDirectory = Path.Combine(root, "proxy");
        var repositoryPath = Path.Combine(root, "repository");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            await DeployProxyAsync(realGit, proxyDirectory, victim);
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
}
