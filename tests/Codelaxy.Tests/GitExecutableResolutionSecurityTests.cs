using System.Diagnostics;
using System.Globalization;
using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitExecutableResolutionSecurityTests
{
    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    private static readonly string GitFileName = OperatingSystem.IsWindows() ? "git.exe" : "git";

    [Fact]
    public void ResolveDefaultGitExecutable_IgnoresWorktreePathEntryReachedThroughDirectorySymlink()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));
        var linkedBin = sandbox.CreateDirectorySymlink(
            Path.Combine(sandbox.Root, "outside", "tools"),
            Path.Combine(repository, "bin")
        );

        var resolved = Resolve(linkedBin, Path.Combine(repository, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_IgnoresWorktreePathEntryReachedThroughJunctionOnWindows()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));
        var junction = sandbox.CreateJunction(
            Path.Combine(sandbox.Root, "outside", "tools"),
            Path.Combine(repository, "bin")
        );

        var resolved = Resolve(junction, Path.Combine(repository, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_IgnoresGitSymlinkPointingIntoWorktree()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));
        var outsideBin = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside", "bin"));

        sandbox.CreateFileSymlink(Path.Combine(outsideBin.FullName, GitFileName), fakeGit);

        var resolved = Resolve(outsideBin.FullName, Path.Combine(repository, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_ProtectsWorktreeWhenStartedThroughSymlink()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));
        var linkedStart = sandbox.CreateDirectorySymlink(
            Path.Combine(sandbox.Root, "outside", "entry"),
            Path.Combine(repository, "src")
        );

        var resolved = Resolve(Path.Combine(repository, "bin"), linkedStart);

        AssertTrustedGit(resolved, fakeGit);
    }

    [Theory]
    [InlineData(@"\\?\")]
    [InlineData(@"\\.\")]
    public void ResolveDefaultGitExecutable_RejectsDevicePrefixedWorktreeGitOnWindows(string prefix)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        var aliasedBin = prefix + Path.Combine(repository, "bin");

        Assert.True(
            File.Exists(Path.Combine(aliasedBin, GitFileName)),
            $"Test alias is inaccessible: '{aliasedBin}'."
        );

        var resolved = Resolve(aliasedBin, Path.Combine(repository, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_RejectsWorktreeGitWhenStartDirectoryHasDevicePrefixOnWindows()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        var aliasedStart = @"\\?\" + Path.Combine(repository, "src");

        Assert.True(
            Directory.Exists(aliasedStart),
            $"Test alias is inaccessible: '{aliasedStart}'."
        );

        var resolved = Resolve(Path.Combine(repository, "bin"), aliasedStart);

        AssertTrustedGit(resolved, fakeGit);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_ProtectsMainWorktreeOfExternalLinkedWorktree()
    {
        using var sandbox = new Sandbox();

        var mainWorktree = sandbox.CreateRepository("main");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(mainWorktree, "bin"));

        var worktreeGitDirectory = Path.Combine(mainWorktree, ".git", "worktrees", "feature");
        Directory.CreateDirectory(worktreeGitDirectory);
        File.WriteAllText(Path.Combine(worktreeGitDirectory, "commondir"), "../..\n");

        var linkedWorktree = Path.Combine(sandbox.Root, "elsewhere", "feature");
        Directory.CreateDirectory(Path.Combine(linkedWorktree, "src"));
        File.WriteAllText(
            Path.Combine(linkedWorktree, ".git"),
            $"gitdir: {worktreeGitDirectory}\n"
        );

        var resolved = Resolve(
            Path.Combine(mainWorktree, "bin"),
            Path.Combine(linkedWorktree, "src")
        );

        AssertTrustedGit(resolved, fakeGit);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ResolveDefaultGitExecutable_RejectsWorktreeGitReachedThroughUncOnWindows(
        bool extended
    )
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        var aliasedBin = ToLocalAdminSharePath(Path.Combine(repository, "bin"), extended);

        Assert.True(
            File.Exists(Path.Combine(aliasedBin, GitFileName)),
            $"UNC test fixture is inaccessible: '{aliasedBin}'."
        );

        var resolved = Resolve(aliasedBin, Path.Combine(repository, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ResolveDefaultGitExecutable_AllowsExternalGitReachedThroughUncOnWindows(
        bool extended
    )
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        sandbox.WriteFakeGit(Path.Combine(sandbox.Root, "external", "bin"));

        var aliasedBin = ToLocalAdminSharePath(
            Path.Combine(sandbox.Root, "external", "bin"),
            extended
        );

        var aliasedGit = Path.Combine(aliasedBin, GitFileName);

        Assert.True(File.Exists(aliasedGit), $"UNC test fixture is inaccessible: '{aliasedGit}'.");

        var resolved = Resolve(aliasedBin, Path.Combine(repository, "src"));

        Assert.Equal(Path.GetFullPath(aliasedGit), resolved);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_ProtectsEnclosingRepositoryOfNestedRepository()
    {
        using var sandbox = new Sandbox();

        var outer = sandbox.CreateRepository("outer");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(outer, "bin"));

        var inner = Path.Combine(outer, "vendor", "inner");
        Directory.CreateDirectory(Path.Combine(inner, ".git"));
        Directory.CreateDirectory(Path.Combine(inner, "src"));

        var resolved = Resolve(Path.Combine(outer, "bin"), Path.Combine(inner, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_AcceptsGitInSiblingDirectorySharingWorktreePrefix()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var siblingGit = sandbox.WriteFakeGit(Path.Combine(sandbox.Root, "repo-tools", "bin"));

        var resolved = Resolve(Path.GetDirectoryName(siblingGit)!, Path.Combine(repository, "src"));

        Assert.Equal(siblingGit, resolved);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_AcceptsGitBelowStartDirectoryOutsideAnyWorktree()
    {
        using var sandbox = new Sandbox();

        // e.g. a per-user Git under the profile while the shell starts in the profile
        var home = Directory.CreateDirectory(Path.Combine(sandbox.Root, "home")).FullName;
        var userGit = sandbox.WriteFakeGit(Path.Combine(home, "apps", "git", "bin"));

        var resolved = Resolve(Path.GetDirectoryName(userGit)!, home);

        Assert.Equal(userGit, resolved);
    }

    [Fact]
    public async Task RunReadOnlyAsync_RefusesPathResolvedGitInsideTargetWorktree()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));
        var outside = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside")).FullName;

        // Resolved from a directory that knows nothing about the repository ...
        var runner = new GitProcessRunner(
            string.Join(Path.PathSeparator, Path.GetDirectoryName(fakeGit), TrustedGitDirectory()),
            outside
        );

        // ... and then pointed at that repository.
        var result = await runner.RunReadOnlyAsync(
            Path.Combine(repository, "src"),
            ["--version"],
            GitCommandTimeout
        );

        Assert.Equal(GitCommandFailureKind.LaunchFailure, result.FailureKind);
        Assert.Contains("Refusing to run Git", result.StandardError, StringComparison.Ordinal);
        Assert.False(File.Exists(fakeGit + ".ran"), "The repository-controlled Git was executed.");
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(2)]
    public async Task RunReadOnlyAsync_RefusesRepositoryGitWithAliasedWorkingDirectoryOnWindows(
        int aliasForm
    )
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        var outside = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside")).FullName;

        // Git is resolved before the runner knows which repository
        // will be used as the working directory.
        var runner = new GitProcessRunner(
            string.Join(Path.PathSeparator, Path.GetDirectoryName(fakeGit), TrustedGitDirectory()),
            outside
        );

        var workingDirectory = Path.Combine(repository, "src");

        var aliasedWorkingDirectory = aliasForm switch
        {
            0 => @"\\?\" + workingDirectory,
            1 => ToLocalAdminSharePath(workingDirectory, extended: false),
            2 => ToLocalAdminSharePath(workingDirectory, extended: true),
            _ => throw new ArgumentOutOfRangeException(nameof(aliasForm)),
        };

        Assert.True(
            Directory.Exists(aliasedWorkingDirectory),
            $"Test alias is inaccessible: '{aliasedWorkingDirectory}'."
        );

        var result = await runner.RunReadOnlyAsync(
            aliasedWorkingDirectory,
            ["--version"],
            GitCommandTimeout
        );

        Assert.Equal(GitCommandFailureKind.LaunchFailure, result.FailureKind);

        Assert.Contains("Refusing to run Git", result.StandardError, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("gitdir: bad\0path\n")]
    [InlineData("gitdir: \0\n")]
    [InlineData("gitdir: ::\\\\?\\\0\n")]
    public void ResolveDefaultGitExecutable_IgnoresInvalidGitdirAndKeepsWorktreeProtected(
        string dotGitContent
    )
    {
        using var sandbox = new Sandbox();

        var worktree = sandbox.CreateLinkedWorktreeWithDotGitFile("worktree", dotGitContent);
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(worktree, "bin"));

        var resolved = Resolve(Path.Combine(worktree, "bin"), Path.Combine(worktree, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Theory]
    [InlineData("..\0..\n")]
    [InlineData("\0\n")]
    public void ResolveDefaultGitExecutable_IgnoresInvalidCommondirAndKeepsWorktreeProtected(
        string commonDirectoryContent
    )
    {
        using var sandbox = new Sandbox();

        var gitDirectory = Path.Combine(sandbox.Root, "main", ".git", "worktrees", "feature");
        Directory.CreateDirectory(gitDirectory);
        File.WriteAllText(Path.Combine(gitDirectory, "commondir"), commonDirectoryContent);

        var worktree = sandbox.CreateLinkedWorktreeWithDotGitFile(
            "feature",
            $"gitdir: {gitDirectory}\n"
        );
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(worktree, "bin"));

        var resolved = Resolve(Path.Combine(worktree, "bin"), Path.Combine(worktree, "src"));

        AssertTrustedGit(resolved, fakeGit);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ResolveDefaultGitExecutable_FailsClosedWhenLinkedMetadataIsLockedOnWindows(
        bool lockCommondir
    )
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var mainWorktree = sandbox.CreateRepository("main");

        var fakeGit = sandbox.WriteFakeGit(Path.Combine(mainWorktree, "bin"));

        Assert.True(File.Exists(fakeGit), "The untrusted Git fixture must exist.");

        var gitDirectory = Path.Combine(mainWorktree, ".git", "worktrees", "feature");

        Directory.CreateDirectory(gitDirectory);

        var commondir = Path.Combine(gitDirectory, "commondir");
        File.WriteAllText(commondir, "../..\n");

        var linkedWorktree = sandbox.CreateLinkedWorktreeWithDotGitFile(
            "feature",
            $"gitdir: {gitDirectory}\n"
        );

        var metadataToLock = lockCommondir ? commondir : Path.Combine(linkedWorktree, ".git");

        using var lockedFile = new FileStream(
            metadataToLock,
            FileMode.Open,
            FileAccess.ReadWrite,
            FileShare.None
        );

        var resolved = Resolve(
            Path.Combine(mainWorktree, "bin"),
            Path.Combine(linkedWorktree, "src")
        );

        // Incomplete root discovery cannot establish trust in any PATH candidate.
        Assert.Null(resolved);
    }

    [Fact]
    public async Task RunReadOnlyAsync_HandlesInvalidLinkedWorktreeMetadataWithoutThrowing()
    {
        using var sandbox = new Sandbox();

        var worktree = sandbox.CreateLinkedWorktreeWithDotGitFile(
            "worktree",
            "gitdir: bad\0path\n"
        );
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(worktree, "bin"));
        var outside = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside")).FullName;

        // A trusted Git still runs against the damaged worktree ...
        var trustedRunner = new GitProcessRunner(TrustedGitDirectory(), outside);

        var trustedResult = await trustedRunner.RunReadOnlyAsync(
            Path.Combine(worktree, "src"),
            ["--version"],
            GitCommandTimeout
        );

        Assert.True(trustedResult.Succeeded, trustedResult.StandardError);

        // ... while a Git inside it is still refused.
        var untrustedRunner = new GitProcessRunner(
            string.Join(Path.PathSeparator, Path.GetDirectoryName(fakeGit), TrustedGitDirectory()),
            outside
        );

        var untrustedResult = await untrustedRunner.RunReadOnlyAsync(
            Path.Combine(worktree, "src"),
            ["--version"],
            GitCommandTimeout
        );

        Assert.Equal(GitCommandFailureKind.LaunchFailure, untrustedResult.FailureKind);
        Assert.Contains(
            "Refusing to run Git",
            untrustedResult.StandardError,
            StringComparison.Ordinal
        );
        Assert.False(File.Exists(fakeGit + ".ran"), "The repository-controlled Git was executed.");
    }

    [Fact]
    public async Task ResolveDefaultGitExecutable_DoesNotBlockOnDotGitFifoOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var nested = Path.Combine(repository, "src", "nested");
        Directory.CreateDirectory(nested);

        var fifo = Path.Combine(repository, "src", ".git");

        using (var mkfifo = Process.Start("mkfifo", [fifo]))
        {
            using var mkfifoDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));

            try
            {
                await mkfifo.WaitForExitAsync(mkfifoDeadline.Token);
            }
            catch (OperationCanceledException)
            {
                try
                {
                    mkfifo.Kill(entireProcessTree: true);
                }
                catch (InvalidOperationException)
                {
                    // mkfifo exited between the deadline and Kill.
                }

                using var killDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

                await mkfifo.WaitForExitAsync(killDeadline.Token);

                throw;
            }

            Assert.Equal(0, mkfifo.ExitCode);
        }

        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        var resolution = Task.Run(() => Resolve(Path.Combine(repository, "bin"), nested));

        try
        {
            var completed = await Task.WhenAny(resolution, Task.Delay(TimeSpan.FromSeconds(10)));

            Assert.Same(resolution, completed);

            AssertTrustedGit(await resolution, fakeGit);
        }
        finally
        {
            if (!resolution.IsCompleted)
            {
                // Release a reader blocked in open(2). Opening for read and write
                // never blocks on Linux (fifo(7)), even when no reader is left.
                await using var writer = new FileStream(fifo, FileMode.Open, FileAccess.ReadWrite);
            }
        }
    }

    [Fact]
    public void ResolveDefaultGitExecutable_PreservesTrailingSpaceInGitdirOnLinux()
    {
        // Win32 path normalization drops trailing spaces itself, so only Unix
        // can tell Git's CR/LF-only stripping apart from a general trim.
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var mainWorktree = sandbox.CreateRepository("main");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(mainWorktree, "bin"));

        var worktreeGitDirectory = Path.Combine(mainWorktree, ".git", "worktrees", "feature ");
        Directory.CreateDirectory(worktreeGitDirectory);
        File.WriteAllText(Path.Combine(worktreeGitDirectory, "commondir"), "../..\n");

        var linkedWorktree = sandbox.CreateLinkedWorktreeWithDotGitFile(
            "feature",
            $"gitdir: {worktreeGitDirectory}\n"
        );

        var resolved = Resolve(
            Path.Combine(mainWorktree, "bin"),
            Path.Combine(linkedWorktree, "src")
        );

        AssertTrustedGit(resolved, fakeGit);
    }

    [Fact]
    public void ObserveDotGit_DistinguishesFileDirectoryAndMissing()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        var linkedWorktree = sandbox.CreateLinkedWorktreeWithDotGitFile(
            "feature",
            "gitdir: invalid\n"
        );

        var outside = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside")).FullName;

        Assert.Equal(
            RepositoryControlledPaths.DotGitObservation.Directory,
            RepositoryControlledPaths.ObserveDotGit(repository)
        );

        Assert.Equal(
            RepositoryControlledPaths.DotGitObservation.File,
            RepositoryControlledPaths.ObserveDotGit(linkedWorktree)
        );

        Assert.Equal(
            RepositoryControlledPaths.DotGitObservation.Missing,
            RepositoryControlledPaths.ObserveDotGit(outside)
        );

        Assert.Equal(
            RepositoryControlledPaths.DotGitObservation.Indeterminate,
            RepositoryControlledPaths.ObserveDotGit(
                Path.Combine(sandbox.Root, "nonexistent-parent")
            )
        );
    }

    [Fact]
    public void ObserveDotGit_DoesNotTrustReparsePointOnWindows()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        var linkedDirectory = Directory
            .CreateDirectory(Path.Combine(sandbox.Root, "linked-directory"))
            .FullName;

        sandbox.CreateDirectorySymlink(
            Path.Combine(linkedDirectory, ".git"),
            Path.Combine(repository, ".git")
        );

        Assert.Equal(
            RepositoryControlledPaths.DotGitObservation.Indeterminate,
            RepositoryControlledPaths.ObserveDotGit(linkedDirectory)
        );
    }

    [Theory]
    [InlineData("gitdir:{0}\n")]
    [InlineData(" gitdir: {0}\n")]
    [InlineData("GITDIR: {0}\n")]
    public void GetProtectedRoots_IgnoresGitdirWithoutExactGitPrefix(string dotGitTemplate)
    {
        using var sandbox = new Sandbox();

        var gitDirectory = Path.Combine(sandbox.Root, "main", ".git", "worktrees", "feature");
        Directory.CreateDirectory(gitDirectory);

        var worktree = sandbox.CreateLinkedWorktreeWithDotGitFile(
            "feature",
            string.Format(CultureInfo.InvariantCulture, dotGitTemplate, gitDirectory)
        );

        var roots = RepositoryControlledPaths.GetProtectedRoots(Path.Combine(worktree, "src"));

        Assert.Contains(Path.GetFullPath(worktree), roots, PathComparer);
        Assert.DoesNotContain(Path.GetFullPath(gitDirectory), roots, PathComparer);
    }

    [Theory]
    [InlineData("\n")]
    [InlineData("\r\n")]
    [InlineData("")]
    public void GetProtectedRoots_AcceptsGitdirTerminatedLikeGit(string terminator)
    {
        using var sandbox = new Sandbox();

        var gitDirectory = Path.Combine(sandbox.Root, "main", ".git", "worktrees", "feature");
        Directory.CreateDirectory(gitDirectory);

        var worktree = sandbox.CreateLinkedWorktreeWithDotGitFile(
            "feature",
            $"gitdir: {gitDirectory}{terminator}"
        );

        var roots = RepositoryControlledPaths.GetProtectedRoots(Path.Combine(worktree, "src"));

        Assert.Contains(Path.GetFullPath(worktree), roots, PathComparer);
        Assert.Contains(Path.GetFullPath(gitDirectory), roots, PathComparer);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ProtectedAncestorMatcher_RecognizesLocalAndUncAliasesOnWindows(bool extended)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        var aliasedGit = ToLocalAdminSharePath(fakeGit, extended);
        var aliasedRoot = ToLocalAdminSharePath(repository, extended);

        Assert.True(File.Exists(aliasedGit));
        Assert.True(Directory.Exists(aliasedRoot));

        Assert.Equal(
            WindowsProtectedAncestorMatcher.MatchResult.Match,
            WindowsProtectedAncestorMatcher.Check(aliasedGit, repository)
        );

        Assert.Equal(
            WindowsProtectedAncestorMatcher.MatchResult.Match,
            WindowsProtectedAncestorMatcher.Check(fakeGit, aliasedRoot)
        );
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ProtectedAncestorMatcher_DistinguishesExternalUncGitOnWindows(bool extended)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        var externalGit = sandbox.WriteFakeGit(Path.Combine(sandbox.Root, "external", "bin"));

        var aliasedGit = ToLocalAdminSharePath(externalGit, extended);

        Assert.True(File.Exists(aliasedGit));

        Assert.Equal(
            WindowsProtectedAncestorMatcher.MatchResult.NoMatch,
            WindowsProtectedAncestorMatcher.Check(aliasedGit, repository)
        );
    }

    [Fact]
    public void ProtectedAncestorMatcher_ReturnsIndeterminateForMissingObjectsOnWindows()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        Assert.Equal(
            WindowsProtectedAncestorMatcher.MatchResult.Indeterminate,
            WindowsProtectedAncestorMatcher.Check(
                fakeGit,
                Path.Combine(sandbox.Root, "missing-root")
            )
        );

        Assert.Equal(
            WindowsProtectedAncestorMatcher.MatchResult.Indeterminate,
            WindowsProtectedAncestorMatcher.Check(
                Path.Combine(repository, "missing", "git.exe"),
                repository
            )
        );
    }

    [Fact]
    public void ProtectedAncestorMatcher_DoesNotTrustUnresolvedDirectorySymlink()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        sandbox.WriteFakeGit(Path.Combine(repository, "bin"));

        var linkedBin = sandbox.CreateDirectorySymlink(
            Path.Combine(sandbox.Root, "outside", "tools"),
            Path.Combine(repository, "bin")
        );

        Assert.Equal(
            WindowsProtectedAncestorMatcher.MatchResult.Indeterminate,
            WindowsProtectedAncestorMatcher.Check(Path.Combine(linkedBin, GitFileName), repository)
        );
    }

    [Fact]
    public void ResolveDefaultGitExecutable_SelectsTrustedGitOutsideRepository()
    {
        using var sandbox = new Sandbox();

        var outside = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside")).FullName;

        var resolved = Resolve(TrustedGitDirectory(), outside);

        Assert.Equal(TrustedGitPath(), resolved, PathComparer);
    }

    private static StringComparer PathComparer =>
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    private static string ToLocalAdminSharePath(string path, bool extended)
    {
        var fullPath = Path.GetFullPath(path);
        var root = Path.GetPathRoot(fullPath);

        if (
            root is null
            || root.Length != 3
            || !char.IsLetter(root[0])
            || root[1] != ':'
            || root[2] != '\\'
        )
        {
            throw new NotSupportedException(
                "UNC test requires a drive-letter-based temporary directory."
            );
        }

        var unc = $@"\\localhost\{char.ToUpperInvariant(root[0])}$" + fullPath[2..];

        return extended ? @"\\?\UNC\" + unc[2..] : unc;
    }

    private static string? Resolve(string firstPathEntry, string startDirectory)
    {
        var pathVariable = string.Join(Path.PathSeparator, firstPathEntry, TrustedGitDirectory());

        return GitProcessRunner.ResolveDefaultGitExecutable(pathVariable, startDirectory);
    }

    private static void AssertTrustedGit(string? resolved, string fakeGit)
    {
        Assert.NotNull(resolved);
        Assert.Equal(Path.GetFullPath(TrustedGitPath()), Path.GetFullPath(resolved));
        Assert.NotEqual(Path.GetFullPath(fakeGit), Path.GetFullPath(resolved));
    }

    private static string TrustedGitPath()
    {
        return new GitProcessRunner()
            .CreateProcessStartInfo(Directory.GetCurrentDirectory(), ["--version"], readOnly: true)
            .FileName;
    }

    private static string TrustedGitDirectory()
    {
        return Path.GetDirectoryName(TrustedGitPath())!;
    }

    private sealed class Sandbox : IDisposable
    {
        private readonly List<string> _links = [];

        public Sandbox()
        {
            Root = Path.Combine(Path.GetTempPath(), $"Codelaxy Resolver Tests {Guid.NewGuid():N}");
            Directory.CreateDirectory(Root);
        }

        public string Root { get; }

        public string CreateRepository(string name)
        {
            var repository = Path.Combine(Root, name);

            Directory.CreateDirectory(Path.Combine(repository, ".git"));
            Directory.CreateDirectory(Path.Combine(repository, "src"));

            return repository;
        }

        public string CreateLinkedWorktreeWithDotGitFile(string name, string dotGitContent)
        {
            var worktree = Path.Combine(Root, name);

            Directory.CreateDirectory(Path.Combine(worktree, "src"));
            File.WriteAllText(Path.Combine(worktree, ".git"), dotGitContent);

            return worktree;
        }

        public string WriteFakeGit(string directory)
        {
            Directory.CreateDirectory(directory);

            var path = Path.Combine(directory, GitFileName);

            File.WriteAllText(path, "#!/bin/sh\n: > \"$0.ran\"\n");

            if (!OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(
                    path,
                    UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
                );
            }

            return path;
        }

        public string CreateDirectorySymlink(string link, string target)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(link)!);
            Directory.CreateSymbolicLink(link, target);
            _links.Add(link);

            return link;
        }

        public void CreateFileSymlink(string link, string target)
        {
            File.CreateSymbolicLink(link, target);
            _links.Add(link);
        }

        public string CreateJunction(string link, string target)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(link)!);

            using var process = Process.Start(
                new ProcessStartInfo("cmd.exe", ["/c", "mklink", "/J", link, target])
                {
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                }
            )!;

            process.WaitForExit();

            Assert.True(process.ExitCode == 0, "mklink /J failed");
            Assert.NotNull(new DirectoryInfo(link).LinkTarget);

            _links.Add(link);

            return link;
        }

        public void Dispose()
        {
            foreach (var link in _links)
            {
                if (Directory.Exists(link))
                {
                    Directory.Delete(link);
                }
                else if (File.Exists(link) || new FileInfo(link).LinkTarget is not null)
                {
                    File.Delete(link);
                }
            }

            if (Directory.Exists(Root))
            {
                Directory.Delete(Root, recursive: true);
            }
        }
    }
}
