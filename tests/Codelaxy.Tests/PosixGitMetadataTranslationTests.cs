using Codelaxy.Git;

namespace Codelaxy.Tests;

// S1-B.5: POSIX paths in Git metadata (MSYS2/Cygwin) are interpreted only through an
// explicitly configured environment root, and only when the gitdir back-link,
// the worktrees layout and the commondir binding are proven by file identity.
// The fixture is a synthetic MSYS2 layout; no MSYS2 installation is required.
public class PosixGitMetadataTranslationTests
{
    internal const string DefaultFstab = "none / cygdrive binary,posix=0,noacl,user 0 0\n";

    // Compatibility: the exact metadata shape MSYS2 Git 2.55.0 wrote in experiment E1.
    [Fact]
    public void Discover_ResolvesMsysTmpMetadataWithConfiguredEnvironment()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, gitDirectory) = fixture.CreateLinkedWorktree(main, "linked3");

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);
        Assert.Contains(Path.GetFullPath(worktree), result.Roots, PathComparer);
        Assert.Contains(Path.GetFullPath(gitDirectory), result.Roots, PathComparer);
        Assert.Contains(Path.GetFullPath(main), result.Roots, PathComparer);
    }

    // Compatibility: drive paths written through the cygdrive prefix ("/c/...").
    [Fact]
    public void Discover_ResolvesCygdriveMetadataWithConfiguredEnvironment()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, gitDirectory) = fixture.CreateLinkedWorktree(
            main,
            "linked",
            gitdirValue: MsysFixture.ToCygdrivePath(
                Path.Combine(main, ".git", "worktrees", "linked")
            )
        );

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);
        Assert.Contains(Path.GetFullPath(gitDirectory), result.Roots, PathComparer);
        Assert.Contains(Path.GetFullPath(main), result.Roots, PathComparer);
    }

    // Security: without a configured environment POSIX metadata stays unresolved.
    [Fact]
    public void Discover_TreatsPosixMetadataWithoutEnvironmentAsIndeterminate()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts: null);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: a Git planted in the main worktree that is only reachable through
    // translated metadata is denied, not merely left indeterminate.
    [Fact]
    public void VerifyDetailed_DeniesGitInsideMainWorktreeResolvedFromPosixMetadata()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var fakeGit = fixture.WriteGit(Path.Combine(main, "bin"));

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            fakeGit,
            Path.Combine(worktree, "src"),
            mounts
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, decision.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Reason.InsideProtectedRoot, decision.Reason);
    }

    // Compatibility: the environment's own Git is allowed once the metadata is proven.
    [Fact]
    public void VerifyDetailed_AllowsEnvironmentGitWithConfiguredEnvironment()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var environmentGit = fixture.WriteGit(Path.Combine(fixture.EnvironmentRoot, "usr", "bin"));

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            environmentGit,
            Path.Combine(worktree, "src"),
            mounts
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, decision.Verdict);
    }

    // Security: a proven POSIX chain describes how the environment's Git reads the
    // metadata. A Git outside that environment may read it differently.
    [Fact]
    public void VerifyDetailed_KeepsExternalGitIndeterminateWithProvenPosixMetadata()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            externalGit,
            Path.Combine(worktree, "src"),
            mounts
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);
        Assert.Equal(
            GitExecutableLocationVerifier.Reason.PosixEnvironmentMismatch,
            decision.Reason
        );
    }

    // Security: unconfigured POSIX metadata never yields Allow for an external Git.
    [Fact]
    public void VerifyDetailed_KeepsExternalGitIndeterminateWithoutEnvironment()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            externalGit,
            Path.Combine(worktree, "src"),
            mounts: null
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Reason.UnmappedPosixMetadata, decision.Reason);
    }

    // Security: a valid but wrong environment root maps the metadata to a place
    // where nothing proves it; the result must stay indeterminate.
    [Fact]
    public void Discover_RejectsMetadataUnderWrongEnvironmentRoot()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var otherRoot = fixture.CreateEnvironment("other");

        var mounts = PosixMountTable.TryLoad(otherRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: under the wrong root the translated path exists, but its back-link
    // names a different worktree. Existence alone must not be accepted.
    [Fact]
    public void Discover_RejectsExistingDecoyUnderWrongEnvironmentRoot()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");

        var otherRoot = fixture.CreateEnvironment("other");
        var decoyMain = fixture.CreateMainRepository("repo", otherRoot);
        fixture.CreateLinkedWorktree(decoyMain, "linked3", worktreeName: "decoy-worktree");

        var mounts = PosixMountTable.TryLoad(otherRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: the back-link must identify this worktree's .git file by identity.
    [Fact]
    public void Discover_RejectsBackLinkNamingAnotherDotGitFile()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (other, _) = fixture.CreateLinkedWorktree(main, "other");
        var (worktree, _) = fixture.CreateLinkedWorktree(
            main,
            "linked3",
            backLink: fixture.ToMsysBackLink(Path.Combine(other, ".git"))
        );

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: a missing or malformed back-link is not proof.
    [Theory]
    [InlineData("missing")]
    [InlineData("empty")]
    [InlineData("directory")]
    [InlineData("invalid")]
    public void Discover_RejectsUnusableBackLink(string kind)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, gitDirectory) = fixture.CreateLinkedWorktree(main, "linked3");
        var backLink = Path.Combine(gitDirectory, "gitdir");

        File.Delete(backLink);

        switch (kind)
        {
            case "empty":
                File.WriteAllText(backLink, string.Empty);
                break;
            case "directory":
                Directory.CreateDirectory(backLink);
                break;
            case "invalid":
                File.WriteAllText(backLink, "bad\0path\n");
                break;
        }

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: a back-link that cannot be read now is not proof.
    [Fact]
    public void Discover_RejectsLockedBackLink()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, gitDirectory) = fixture.CreateLinkedWorktree(main, "linked3");

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        using var locked = new FileStream(
            Path.Combine(gitDirectory, "gitdir"),
            FileMode.Open,
            FileAccess.ReadWrite,
            FileShare.None
        );

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: commondir must name the directory that holds worktrees\<id>.
    [Fact]
    public void Discover_RejectsCommondirNotBoundToWorktreesLayout()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var decoy = fixture.CreateMainRepository("decoy");
        var (worktree, _) = fixture.CreateLinkedWorktree(
            main,
            "linked3",
            commondir: Path.Combine(decoy, ".git")
        );

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: a translated gitdir outside <common>\worktrees\<id> is not accepted.
    [Fact]
    public void Discover_RejectsTranslatedGitDirectoryOutsideWorktreesLayout()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var storage = Path.Combine(fixture.EnvironmentRoot, "tmp", "storage", "linked3");
        var worktree = Path.Combine(fixture.EnvironmentRoot, "tmp", "linked3");

        Directory.CreateDirectory(storage);
        Directory.CreateDirectory(Path.Combine(worktree, "src"));
        File.WriteAllText(Path.Combine(storage, "commondir"), "../..\n");
        File.WriteAllText(
            Path.Combine(storage, "gitdir"),
            fixture.ToMsysBackLink(Path.Combine(worktree, ".git")) + "\n"
        );
        File.WriteAllText(
            Path.Combine(worktree, ".git"),
            $"gitdir: {fixture.ToPosixPath(storage)}\n"
        );

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security (adversarial metadata): a self-consistent decoy chain cannot be told
    // apart from genuine metadata, but it can never unprotect the worktree the
    // command runs in.
    [Fact]
    public void VerifyDetailed_DeniesGitInsideWorktreeDespiteConsistentDecoyMetadata()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var decoyMain = fixture.CreateMainRepository("decoy");
        var (worktree, _) = fixture.CreateLinkedWorktree(decoyMain, "linked3");
        var fakeGit = fixture.WriteGit(Path.Combine(worktree, "bin"));

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            fakeGit,
            Path.Combine(worktree, "src"),
            mounts
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, decision.Verdict);
    }

    // Security (adversarial metadata): whatever a consistent chain names becomes
    // protected; it cannot be used to whitelist a Git inside that chain.
    [Fact]
    public void VerifyDetailed_DeniesGitInsideConsistentDecoyChain()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var decoyMain = fixture.CreateMainRepository("decoy");
        var (worktree, _) = fixture.CreateLinkedWorktree(decoyMain, "linked3");
        var fakeGit = fixture.WriteGit(Path.Combine(decoyMain, "bin"));

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            fakeGit,
            Path.Combine(worktree, "src"),
            mounts
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, decision.Verdict);
    }

    // Security: proven Deny wins over incomplete discovery (no environment configured).
    [Fact]
    public void VerifyDetailed_DeniesGitInsideWorktreeWhenPosixDiscoveryIsIncomplete()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var fakeGit = fixture.WriteGit(Path.Combine(worktree, "bin"));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            fakeGit,
            Path.Combine(worktree, "src"),
            mounts: null
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, decision.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Reason.InsideProtectedRoot, decision.Reason);
    }

    // Compatibility (O2): "/tmp" mounted as usertemp maps to the current user's TEMP
    // and is accepted when the back-link proves it.
    [Fact]
    public void Discover_ResolvesUserTempMountWithProvenBackLink()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture(
            DefaultFstab + "none /tmp usertemp binary,posix=0,noacl 0 0\n"
        );

        var main = fixture.CreateMainRepository("repo");
        var gitDirectory = Path.Combine(main, ".git", "worktrees", "linked3");
        var (worktree, _) = fixture.CreateLinkedWorktree(
            main,
            "linked3",
            gitdirValue: "/tmp/"
                + Path.GetRelativePath(Path.GetTempPath(), gitDirectory).Replace('\\', '/')
        );

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);
        Assert.Contains(Path.GetFullPath(main), result.Roots, PathComparer);
    }

    // Security (O2): with usertemp, "/tmp/<x>" does not mean <root>\tmp\<x>.
    [Fact]
    public void Discover_RejectsRootTmpPathWhenTmpIsUserTemp()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture(
            DefaultFstab + "none /tmp usertemp binary,posix=0,noacl 0 0\n"
        );

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");

        var mounts = PosixMountTable.TryLoad(fixture.EnvironmentRoot);

        Assert.NotNull(mounts);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"), mounts);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    // Security: an environment that cannot be interpreted completely is not usable.
    [Theory]
    [InlineData("no-fstab")]
    [InlineData("fstab-d")]
    [InlineData("unknown-option")]
    [InlineData("unknown-line")]
    [InlineData("no-runtime")]
    [InlineData("missing-root")]
    public void TryLoad_RejectsUnusableEnvironment(string kind)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var root = fixture.EnvironmentRoot;

        switch (kind)
        {
            case "no-fstab":
                File.Delete(Path.Combine(root, "etc", "fstab"));
                break;
            case "fstab-d":
                Directory.CreateDirectory(Path.Combine(root, "etc", "fstab.d"));
                File.WriteAllText(Path.Combine(root, "etc", "fstab.d", "user"), DefaultFstab);
                break;
            case "unknown-option":
                File.WriteAllText(
                    Path.Combine(root, "etc", "fstab"),
                    "none / cygdrive binary,posix=0,noacl,user,mystery 0 0\n"
                );
                break;
            case "unknown-line":
                File.WriteAllText(Path.Combine(root, "etc", "fstab"), DefaultFstab + "garbage\n");
                break;
            case "no-runtime":
                File.Delete(Path.Combine(root, "usr", "bin", "msys-2.0.dll"));
                break;
            case "missing-root":
                root = Path.Combine(fixture.Root, "does-not-exist");
                break;
        }

        Assert.Null(PosixMountTable.TryLoad(root));
    }

    // Security: an environment root reached through a reparse point is not usable.
    [Fact]
    public void TryLoad_RejectsEnvironmentRootBehindSymlink()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var alias = Path.Combine(fixture.Root, "alias");

        Directory.CreateSymbolicLink(alias, fixture.EnvironmentRoot);

        Assert.Null(PosixMountTable.TryLoad(alias));
    }

    // Compatibility (Linux): POSIX gitdir values are native and need no environment.
    [Fact]
    public void Discover_TreatsPosixGitdirAsNativeOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var root = Path.Combine(Path.GetTempPath(), $"Codelaxy Posix {Guid.NewGuid():N}");

        try
        {
            var main = Path.Combine(root, "main");
            var gitDirectory = Path.Combine(main, ".git", "worktrees", "linked");
            var worktree = Path.Combine(root, "linked");

            Directory.CreateDirectory(gitDirectory);
            Directory.CreateDirectory(Path.Combine(worktree, "src"));
            File.WriteAllText(Path.Combine(gitDirectory, "commondir"), "../..\n");
            File.WriteAllText(Path.Combine(worktree, ".git"), $"gitdir: {gitDirectory}\n");

            var result = ProtectedRootDiscovery.Discover(
                Path.Combine(worktree, "src"),
                mounts: null
            );

            Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);
            Assert.Contains(main, result.Roots, PathComparer);
            Assert.Null(PosixMountTable.TryLoad(root));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static StringComparer PathComparer =>
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    // A synthetic MSYS2 installation: <root>\usr\bin\msys-2.0.dll, <root>\etc\fstab,
    // repositories under <root>\tmp exactly like experiment E1.
    internal sealed class MsysFixture : IDisposable
    {
        public MsysFixture(string fstab = DefaultFstab)
        {
            Root = Path.Combine(Path.GetTempPath(), $"Codelaxy Posix {Guid.NewGuid():N}");
            EnvironmentRoot = CreateEnvironment("msys", fstab);
        }

        public string Root { get; }

        public string EnvironmentRoot { get; }

        public string CreateEnvironment(string name, string fstab = DefaultFstab)
        {
            var environment = Path.Combine(Root, name);

            Directory.CreateDirectory(Path.Combine(environment, "usr", "bin"));
            Directory.CreateDirectory(Path.Combine(environment, "etc"));
            Directory.CreateDirectory(Path.Combine(environment, "tmp"));
            File.WriteAllBytes(Path.Combine(environment, "usr", "bin", "msys-2.0.dll"), []);
            File.WriteAllText(Path.Combine(environment, "etc", "fstab"), fstab);

            return environment;
        }

        public string CreateMainRepository(string name, string? environmentRoot = null)
        {
            var main = Path.Combine(environmentRoot ?? EnvironmentRoot, "tmp", name);

            Directory.CreateDirectory(Path.Combine(main, ".git"));
            Directory.CreateDirectory(Path.Combine(main, "src"));

            return main;
        }

        // Mirrors E1: .git holds a POSIX gitdir, the back-link is a mixed Windows path,
        // commondir is relative.
        public (string Worktree, string GitDirectory) CreateLinkedWorktree(
            string main,
            string id,
            string? worktreeName = null,
            string? gitdirValue = null,
            string? backLink = null,
            string commondir = "../.."
        )
        {
            var environmentRoot = Path.GetDirectoryName(Path.GetDirectoryName(main))!;
            var worktree = Path.Combine(environmentRoot, "tmp", worktreeName ?? id);
            var gitDirectory = Path.Combine(main, ".git", "worktrees", id);

            Directory.CreateDirectory(gitDirectory);
            Directory.CreateDirectory(Path.Combine(worktree, "src"));

            File.WriteAllText(Path.Combine(gitDirectory, "commondir"), commondir + "\n");
            File.WriteAllText(
                Path.Combine(gitDirectory, "gitdir"),
                (backLink ?? ToMsysBackLink(Path.Combine(worktree, ".git"), environmentRoot)) + "\n"
            );
            File.WriteAllText(
                Path.Combine(worktree, ".git"),
                $"gitdir: {gitdirValue ?? ToPosixPath(gitDirectory, environmentRoot)}\n"
            );

            return (worktree, gitDirectory);
        }

        public string WriteGit(string directory)
        {
            Directory.CreateDirectory(directory);

            var executable = Path.Combine(directory, "git.exe");

            File.WriteAllText(executable, "test fixture");

            return executable;
        }

        // <root>\tmp\a\b -> /tmp/a/b
        public string ToPosixPath(string path, string? environmentRoot = null) =>
            "/" + Path.GetRelativePath(environmentRoot ?? EnvironmentRoot, path).Replace('\\', '/');

        // E1 shape: C:\...\msys/tmp/a/.git
        public string ToMsysBackLink(string path, string? environmentRoot = null)
        {
            var root = environmentRoot ?? EnvironmentRoot;

            return root + "/" + Path.GetRelativePath(root, path).Replace('\\', '/');
        }

        // C:\a\b -> /c/a/b
        public static string ToCygdrivePath(string path) =>
            "/" + char.ToLowerInvariant(path[0]) + path[2..].Replace('\\', '/');

        public void Dispose()
        {
            if (Directory.Exists(Root))
            {
                Directory.Delete(Root, recursive: true);
            }
        }
    }
}
