using System.Diagnostics;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;
using Codelaxy.Git;
using MsysFixture = Codelaxy.Tests.PosixGitMetadataTranslationTests.MsysFixture;

namespace Codelaxy.Tests;

// S1-B.5: CODELAXY_GIT_ENVIRONMENT_ROOT reaches the PATH resolver and the launch guard
// as one explicitly configured environment. It never weakens Deny or Indeterminate,
// it can only narrow Allow, and an unusable value refuses instead of falling back.
public class GitEnvironmentRootTests
{
    // Binding compares file identity, not path text: an alias of the environment's
    // own Git is still that Git.
    [Fact]
    public void VerifyDetailed_AllowsEnvironmentGitThroughLocalShareAlias()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var environmentGit = fixture.WriteGit(Path.Combine(fixture.EnvironmentRoot, "usr", "bin"));
        var alias = ToLocalAdminSharePath(environmentGit);

        Assert.True(File.Exists(alias));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            alias,
            Path.Combine(worktree, "src"),
            LoadMounts(fixture.EnvironmentRoot)
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, decision.Verdict);
    }

    // Security: a hard link of the environment's Git in another directory is the same
    // file but would load another runtime, so the directory identity must match too.
    [Fact]
    public void VerifyDetailed_KeepsHardLinkedEnvironmentGitElsewhereIndeterminate()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var environmentGit = fixture.WriteGit(Path.Combine(fixture.EnvironmentRoot, "usr", "bin"));
        var hardLink = Path.Combine(fixture.Root, "external", "bin", "git.exe");

        RunMklink("/H", hardLink, environmentGit);

        Assert.True(WindowsFileIdentity.TryRead(hardLink, out var linkIdentity));
        Assert.True(WindowsFileIdentity.TryRead(environmentGit, out var gitIdentity));
        Assert.Equal(gitIdentity, linkIdentity);

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            hardLink,
            Path.Combine(worktree, "src"),
            LoadMounts(fixture.EnvironmentRoot)
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);
        Assert.Equal(
            GitExecutableLocationVerifier.Reason.PosixEnvironmentMismatch,
            decision.Reason
        );
    }

    // Security: a valid but wrong environment proves nothing and says so.
    [Fact]
    public void VerifyDetailed_ReportsUnprovenMetadataUnderWrongEnvironment()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var other = fixture.CreateEnvironment("other");
        var otherGit = fixture.WriteGit(Path.Combine(other, "usr", "bin"));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            otherGit,
            Path.Combine(worktree, "src"),
            LoadMounts(other)
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Reason.UnprovenPosixMetadata, decision.Reason);
    }

    // Compatibility (Git for Windows): native metadata never consults the mount table,
    // so a configured environment changes nothing there.
    [Fact]
    public void VerifyDetailed_KeepsNativeMetadataIndependentOfEnvironment()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(
            main,
            "native",
            gitdirValue: Path.Combine(main, ".git", "worktrees", "native")
        );
        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));

        var without = GitExecutableLocationVerifier.VerifyDetailed(
            externalGit,
            Path.Combine(worktree, "src"),
            mounts: null
        );

        var with = GitExecutableLocationVerifier.VerifyDetailed(
            externalGit,
            Path.Combine(worktree, "src"),
            LoadMounts(fixture.EnvironmentRoot)
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, without.Verdict);
        Assert.Equal(without, with);
    }

    // Security: supplying an environment only adds what it proves. Every root found
    // without it is still found with it, and a complete discovery stays complete.
    [Theory]
    [MemberData(nameof(Scenarios))]
    public void Discover_EnvironmentNeverDropsRootsFoundWithoutIt(string scenario)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var (directory, mounts) = CreateScenario(fixture, scenario);

        var without = ProtectedRootDiscovery.Discover(directory, mounts: null);
        var with = ProtectedRootDiscovery.Discover(directory, mounts);

        Assert.NotEmpty(without.Roots);
        Assert.All(without.Roots, root => Assert.Contains(root, with.Roots, PathComparer));

        if (without.Status == ProtectedRootDiscovery.DiscoveryStatus.Complete)
        {
            Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, with.Status);
        }
    }

    // Security: the same property at the decision. A Git denied without the
    // environment stays denied with it, wherever in those roots it was planted.
    [Theory]
    [MemberData(nameof(Scenarios))]
    public void VerifyDetailed_EnvironmentNeverLiftsDenyFoundWithoutIt(string scenario)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var (directory, mounts) = CreateScenario(fixture, scenario);
        var roots = ProtectedRootDiscovery.Discover(directory, mounts: null).Roots;

        Assert.NotEmpty(roots);

        foreach (var root in roots)
        {
            var plantedGit = fixture.WriteGit(Path.Combine(root, "planted"));

            Assert.Equal(
                GitExecutableLocationVerifier.Verdict.Deny,
                GitExecutableLocationVerifier
                    .VerifyDetailed(plantedGit, directory, mounts: null)
                    .Verdict
            );

            Assert.Equal(
                GitExecutableLocationVerifier.Verdict.Deny,
                GitExecutableLocationVerifier.VerifyDetailed(plantedGit, directory, mounts).Verdict
            );
        }
    }

    // Security: configuration pointing into the observed repository is not explicit
    // configuration any more; the repository could rewrite the mount table.
    [Fact]
    public void VerifyDetailed_RejectsEnvironmentInsideObservedRepository()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var planted = CreateEnvironmentAt(fixture, Path.Combine(main, "tools", "msys"));
        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));

        var without = GitExecutableLocationVerifier.VerifyDetailed(
            externalGit,
            Path.Combine(main, "src"),
            mounts: null
        );

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            externalGit,
            Path.Combine(main, "src"),
            LoadMounts(planted)
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, without.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);
        Assert.Equal(
            GitExecutableLocationVerifier.Reason.UntrustedPosixEnvironment,
            decision.Reason
        );
    }

    // Security: the same when the environment sits in a main worktree that only the
    // metadata it interprets leads to.
    [Fact]
    public void VerifyDetailed_RejectsEnvironmentInsideTranslatedChain()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var (worktree, main) = CreateCygdriveLinkedWorktree(fixture);
        var planted = CreateEnvironmentAt(fixture, Path.Combine(main, "tools", "msys"));
        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            externalGit,
            Path.Combine(worktree, "src"),
            LoadMounts(planted)
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);
        Assert.Equal(
            GitExecutableLocationVerifier.Reason.UntrustedPosixEnvironment,
            decision.Reason
        );
    }

    // Security: when the configured root can no longer be placed relative to the
    // repository (it became a junction after it was loaded), nothing is allowed.
    [Fact]
    public void VerifyDetailed_RejectsEnvironmentWhoseLocationCannotBeVerified()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var repository = Path.Combine(fixture.Root, "plain", "repo");

        Directory.CreateDirectory(Path.Combine(repository, ".git"));
        Directory.CreateDirectory(Path.Combine(repository, "src"));

        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));
        var mounts = LoadMounts(fixture.EnvironmentRoot);
        var moved = fixture.EnvironmentRoot + "-moved";

        Directory.Move(fixture.EnvironmentRoot, moved);
        RunMklink("/J", fixture.EnvironmentRoot, moved);

        GitExecutableLocationVerifier.Decision without;
        GitExecutableLocationVerifier.Decision decision;

        try
        {
            without = GitExecutableLocationVerifier.VerifyDetailed(
                externalGit,
                Path.Combine(repository, "src"),
                mounts: null
            );

            decision = GitExecutableLocationVerifier.VerifyDetailed(
                externalGit,
                Path.Combine(repository, "src"),
                mounts
            );
        }
        finally
        {
            // A junction is removed on its own; a recursive delete refuses it.
            Directory.Delete(fixture.EnvironmentRoot);
        }

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, without.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Reason.UnverifiableLocation, decision.Reason);
    }

    // Security: Deny keeps precedence; the planted environment's own Git is denied.
    [Fact]
    public void VerifyDetailed_DeniesGitOfEnvironmentInsideTranslatedChain()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var (worktree, main) = CreateCygdriveLinkedWorktree(fixture);
        var planted = CreateEnvironmentAt(fixture, Path.Combine(main, "tools", "msys"));
        var plantedGit = fixture.WriteGit(Path.Combine(planted, "usr", "bin"));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            plantedGit,
            Path.Combine(worktree, "src"),
            LoadMounts(planted)
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, decision.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Reason.InsideProtectedRoot, decision.Reason);
    }

    // Security: an explicit root must be a plain path on a local drive. Aliases,
    // shares and anything that is not a complete MSYS2 layout are refused with a reason.
    [Theory]
    [InlineData("relative", "local drive")]
    [InlineData("drive-relative", "local drive")]
    [InlineData("posix", "local drive")]
    [InlineData("whitespace", "local drive")]
    [InlineData("local-share", "local drive")]
    [InlineData("device-path", "local drive")]
    [InlineData("missing", "is missing, not a directory, or a link")]
    [InlineData("no-runtime", @"usr\bin\msys-2.0.dll' is missing")]
    [InlineData("no-fstab", @"etc\fstab' is missing")]
    [InlineData("fstab-d", @"etc\fstab.d' is not empty")]
    [InlineData("unsupported-line", "line 2 is not supported: garbage")]
    [InlineData("repeated-mount", "repeats a mount point")]
    public void TryLoad_ExplainsUnusableEnvironment(string kind, string expected)
    {
        using var fixture = new MsysFixture();

        var root = fixture.EnvironmentRoot;
        var fstab = Path.Combine(root, "etc", "fstab");

        switch (kind)
        {
            case "relative":
                root = "msys64";
                break;
            case "drive-relative":
                root = "C:msys64";
                break;
            case "posix":
                root = "/c/msys64";
                break;
            case "whitespace":
                root = "   ";
                break;
            case "local-share":
                root = ToLocalAdminSharePath(root);
                break;
            case "device-path":
                root = @"\\?\" + root;
                break;
            case "missing":
                root = Path.Combine(fixture.Root, "missing");
                break;
            case "no-runtime":
                File.Delete(Path.Combine(root, "usr", "bin", "msys-2.0.dll"));
                break;
            case "no-fstab":
                File.Delete(fstab);
                break;
            case "fstab-d":
                Directory.CreateDirectory(Path.Combine(root, "etc", "fstab.d"));
                File.WriteAllText(Path.Combine(root, "etc", "fstab.d", "user"), "");
                break;
            case "unsupported-line":
                File.WriteAllText(
                    fstab,
                    PosixGitMetadataTranslationTests.DefaultFstab + "garbage\n"
                );
                break;
            case "repeated-mount":
                File.WriteAllText(
                    fstab,
                    PosixGitMetadataTranslationTests.DefaultFstab
                        + "none /tmp usertemp binary,posix=0,noacl 0 0\n"
                        + "none /tmp usertemp binary,posix=0,noacl 0 0\n"
                );
                break;
        }

        var mounts = PosixMountTable.TryLoad(root, out var problem);

        Assert.Null(mounts);
        Assert.Contains(
            OperatingSystem.IsWindows() ? expected : "supported only on Windows",
            problem,
            StringComparison.Ordinal
        );
    }

    // Security: everything under the root must be plain too. Windows reports a file
    // reached through a junctioned parent as a regular file, so every directory on the
    // way to etc\fstab and usr\bin\msys-2.0.dll is checked, and etc\fstab.d must be
    // missing or a readable, plain, empty directory.
    [Theory]
    [InlineData(
        "etc-junction",
        @"etc\fstab' is missing, not a regular file, or reached through a link"
    )]
    [InlineData(
        "usr-junction",
        @"msys-2.0.dll' is missing, not a regular file, or reached through a link"
    )]
    [InlineData(
        "bin-junction",
        @"msys-2.0.dll' is missing, not a regular file, or reached through a link"
    )]
    [InlineData(
        "fstab-symlink",
        @"etc\fstab' is missing, not a regular file, or reached through a link"
    )]
    [InlineData(
        "runtime-directory",
        @"msys-2.0.dll' is missing, not a regular file, or reached through a link"
    )]
    [InlineData("fstab-d-file", @"etc\fstab.d' is not a plain directory")]
    [InlineData("fstab-d-junction", @"etc\fstab.d' is not a plain directory")]
    [InlineData("fstab-d-unreadable", "the environment cannot be read")]
    public void TryLoad_RejectsLinkedOrIrregularLayout(string kind, string expected)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var root = fixture.EnvironmentRoot;
        var fstab = Path.Combine(root, "etc", "fstab");
        var fstabDirectory = Path.Combine(root, "etc", "fstab.d");
        var runtime = Path.Combine(root, "usr", "bin", "msys-2.0.dll");
        var junctions = new List<string>();
        var denied = (DirectoryInfo?)null;

        try
        {
            switch (kind)
            {
                case "etc-junction":
                    junctions.Add(MoveBehindJunction(fixture, Path.Combine(root, "etc")));
                    break;
                case "usr-junction":
                    junctions.Add(MoveBehindJunction(fixture, Path.Combine(root, "usr")));
                    break;
                case "bin-junction":
                    junctions.Add(MoveBehindJunction(fixture, Path.Combine(root, "usr", "bin")));
                    break;
                case "fstab-symlink":
                    File.Move(fstab, Path.Combine(fixture.Root, "real-fstab"));
                    File.CreateSymbolicLink(fstab, Path.Combine(fixture.Root, "real-fstab"));
                    break;
                case "runtime-directory":
                    File.Delete(runtime);
                    Directory.CreateDirectory(runtime);
                    break;
                case "fstab-d-file":
                    File.WriteAllText(fstabDirectory, "");
                    break;
                case "fstab-d-junction":
                    RunMklink(
                        "/J",
                        fstabDirectory,
                        Directory.CreateDirectory(Path.Combine(fixture.Root, "empty")).FullName
                    );
                    junctions.Add(fstabDirectory);
                    break;
                case "fstab-d-unreadable":
                    denied = Directory.CreateDirectory(fstabDirectory);
                    SetListDirectoryDenied(denied, denied: true);
                    break;
            }

            var mounts = PosixMountTable.TryLoad(root, out var problem);

            Assert.Null(mounts);
            Assert.Contains(expected, problem, StringComparison.Ordinal);
        }
        finally
        {
            if (denied is not null)
            {
                SetListDirectoryDenied(denied, denied: false);
            }

            foreach (var junction in junctions)
            {
                Directory.Delete(junction);
            }
        }
    }

    // Compatibility: an existing, plain and empty etc\fstab.d is accepted.
    [Fact]
    public void TryLoad_AcceptsEmptyPlainFstabDirectory()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        Directory.CreateDirectory(Path.Combine(fixture.EnvironmentRoot, "etc", "fstab.d"));

        Assert.NotNull(PosixMountTable.TryLoad(fixture.EnvironmentRoot));
    }

    // Security: an unusable explicit configuration refuses every command and never
    // falls back to the Git on PATH, even though that Git would be accepted.
    [Theory]
    [InlineData("msys64")]
    [InlineData("C:msys64")]
    [InlineData("/c/msys64")]
    [InlineData("   ")]
    [InlineData("missing")]
    [InlineData("not-msys")]
    public async Task RunAsync_RefusesUnusableEnvironmentRootWithoutFallback(string value)
    {
        using var fixture = new MsysFixture();

        var root = value switch
        {
            "missing" => Path.Combine(fixture.Root, "missing"),
            "not-msys" => fixture.Root,
            _ => value,
        };

        var path = Environment.GetEnvironmentVariable("PATH");
        var directory = Environment.CurrentDirectory;
        var runner = new GitProcessRunner(path, directory, root);

        var result = await runner.RunAsync(directory, ["--version"]);

        Assert.False(result.Started);
        Assert.Equal(GitCommandFailureKind.LaunchFailure, result.FailureKind);
        Assert.Contains(
            $"{GitProcessRunner.GitEnvironmentRootVariable} '{root}'",
            result.StandardError,
            StringComparison.Ordinal
        );
        Assert.Contains(
            "Git was not searched on PATH",
            result.StandardError,
            StringComparison.Ordinal
        );

        Assert.Throws<InvalidOperationException>(() =>
            runner.CreateProcessStartInfo(directory, ["--version"], readOnly: true)
        );

        var unconfigured = await new GitProcessRunner(
            path,
            directory,
            gitEnvironmentRoot: null
        ).RunAsync(directory, ["--version"]);

        Assert.True(unconfigured.Succeeded, unconfigured.StandardError);
    }

    // Compatibility: an empty value means nothing is configured.
    [Fact]
    public async Task RunAsync_TreatsEmptyEnvironmentRootAsUnset()
    {
        var directory = Environment.CurrentDirectory;
        var runner = new GitProcessRunner(
            Environment.GetEnvironmentVariable("PATH"),
            directory,
            string.Empty
        );

        var result = await runner.RunAsync(directory, ["--version"]);

        Assert.True(result.Succeeded, result.StandardError);
    }

    // The PATH resolver uses the configured environment: started inside an MSYS2
    // linked worktree it skips a Git planted there and selects the environment's Git.
    [Fact]
    public void Constructor_ResolvesEnvironmentGitFromPosixLinkedWorktree()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var plantedGit = fixture.WriteGit(Path.Combine(worktree, "bin"));
        var environmentGit = fixture.WriteGit(Path.Combine(fixture.EnvironmentRoot, "usr", "bin"));
        var directory = Path.Combine(worktree, "src");

        var runner = new GitProcessRunner(
            string.Join(
                Path.PathSeparator,
                Path.GetDirectoryName(plantedGit),
                Path.GetDirectoryName(environmentGit)
            ),
            directory,
            fixture.EnvironmentRoot
        );

        var startInfo = runner.CreateProcessStartInfo(directory, ["--version"], readOnly: true);

        Assert.Equal(Path.GetFullPath(environmentGit), startInfo.FileName, PathComparer);
    }

    // Without the environment the same resolver explains what is missing instead of
    // reporting that no Git exists.
    [Fact]
    public async Task RunAsync_ExplainsMissingEnvironmentForPosixLinkedWorktree()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var environmentGit = fixture.WriteGit(Path.Combine(fixture.EnvironmentRoot, "usr", "bin"));
        var directory = Path.Combine(worktree, "src");

        var runner = new GitProcessRunner(
            Path.GetDirectoryName(environmentGit),
            directory,
            gitEnvironmentRoot: null
        );

        var result = await runner.RunAsync(directory, ["--version"]);

        Assert.False(result.Started);
        Assert.Equal(GitCommandFailureKind.LaunchFailure, result.FailureKind);
        Assert.Contains("(UnmappedPosixMetadata)", result.StandardError, StringComparison.Ordinal);
        Assert.Contains(
            $"export {GitProcessRunner.GitEnvironmentRootVariable}=\"$(cygpath -w /)\"",
            result.StandardError,
            StringComparison.Ordinal
        );
        Assert.DoesNotContain(
            "Unable to locate Git",
            result.StandardError,
            StringComparison.Ordinal
        );
    }

    // The launch guard checks the command's repository with the same environment as
    // the resolver: a runner started outside any repository may operate on an MSYS2
    // linked worktree only when the environment is configured.
    [Fact]
    public async Task RunAsync_GuardUsesConfiguredEnvironmentForTargetRepository()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var environmentGit = fixture.WriteGit(Path.Combine(fixture.EnvironmentRoot, "usr", "bin"));
        var outside = Directory.CreateDirectory(Path.Combine(fixture.Root, "outside")).FullName;
        var target = Path.Combine(worktree, "src");

        var unconfigured = await new GitProcessRunner(
            Path.GetDirectoryName(environmentGit),
            outside,
            gitEnvironmentRoot: null
        ).RunAsync(target, ["--version"]);

        Assert.Contains(
            "(UnmappedPosixMetadata)",
            unconfigured.StandardError,
            StringComparison.Ordinal
        );

        // The fixture Git is not a real program: passing the guard surfaces as an
        // operating-system launch error, not as a refusal.
        var configured = await new GitProcessRunner(
            Path.GetDirectoryName(environmentGit),
            outside,
            fixture.EnvironmentRoot
        ).RunAsync(target, ["--version"]);

        Assert.False(configured.Started);
        Assert.Equal(GitCommandFailureKind.LaunchFailure, configured.FailureKind);
        Assert.DoesNotContain(
            "Refusing to run Git",
            configured.StandardError,
            StringComparison.Ordinal
        );
    }

    // Security: with POSIX metadata the guard refuses a Git that does not belong to the
    // configured environment, and names the one that would.
    [Fact]
    public async Task RunAsync_RefusesGitOutsideConfiguredEnvironment()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));
        var outside = Directory.CreateDirectory(Path.Combine(fixture.Root, "outside")).FullName;

        var result = await new GitProcessRunner(
            Path.GetDirectoryName(externalGit),
            outside,
            fixture.EnvironmentRoot
        ).RunAsync(Path.Combine(worktree, "src"), ["--version"]);

        Assert.False(result.Started);
        Assert.Contains(
            "(PosixEnvironmentMismatch)",
            result.StandardError,
            StringComparison.Ordinal
        );
        Assert.Contains(
            $"'{fixture.EnvironmentRoot}\\usr\\bin\\git.exe'",
            result.StandardError,
            StringComparison.Ordinal
        );
    }

    // Security: the refusal for a planted environment names the configuration.
    [Fact]
    public async Task RunAsync_ExplainsEnvironmentInsideObservedRepository()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var fixture = new MsysFixture();

        var main = fixture.CreateMainRepository("repo");
        var planted = CreateEnvironmentAt(fixture, Path.Combine(main, "tools", "msys"));
        var externalGit = fixture.WriteGit(Path.Combine(fixture.Root, "external", "bin"));
        var outside = Directory.CreateDirectory(Path.Combine(fixture.Root, "outside")).FullName;

        var result = await new GitProcessRunner(
            Path.GetDirectoryName(externalGit),
            outside,
            planted
        ).RunAsync(Path.Combine(main, "src"), ["--version"]);

        Assert.False(result.Started);
        Assert.Contains(
            "(UntrustedPosixEnvironment)",
            result.StandardError,
            StringComparison.Ordinal
        );
        Assert.Contains(
            $"{GitProcessRunner.GitEnvironmentRootVariable} '{planted}' lies inside",
            result.StandardError,
            StringComparison.Ordinal
        );
    }

    public static TheoryData<string> Scenarios =>
        new()
        {
            "proven",
            "inner-repository",
            "outer-repository",
            "wrong-environment",
            "foreign-back-link",
            "native",
        };

    // Each scenario returns the observed directory and the environment to compare
    // against no environment at all.
    private static (string Directory, PosixMountTable Mounts) CreateScenario(
        MsysFixture fixture,
        string scenario
    )
    {
        var main = fixture.CreateMainRepository("repo");
        var mounts = LoadMounts(fixture.EnvironmentRoot);

        switch (scenario)
        {
            case "proven":
            {
                var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
                return (Path.Combine(worktree, "src"), mounts);
            }

            case "inner-repository":
            {
                var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
                var inner = Path.Combine(worktree, "inner");
                Directory.CreateDirectory(Path.Combine(inner, ".git"));
                Directory.CreateDirectory(Path.Combine(inner, "src"));
                return (Path.Combine(inner, "src"), mounts);
            }

            case "outer-repository":
            {
                var outer = Path.Combine(fixture.EnvironmentRoot, "tmp", "outer");
                Directory.CreateDirectory(Path.Combine(outer, ".git"));
                var (worktree, _) = fixture.CreateLinkedWorktree(
                    main,
                    "linked3",
                    worktreeName: Path.Combine("outer", "linked3")
                );
                return (Path.Combine(worktree, "src"), mounts);
            }

            case "wrong-environment":
            {
                var (worktree, _) = fixture.CreateLinkedWorktree(main, "linked3");
                return (
                    Path.Combine(worktree, "src"),
                    LoadMounts(fixture.CreateEnvironment("other"))
                );
            }

            case "foreign-back-link":
            {
                var other = fixture.CreateMainRepository("other");
                File.WriteAllText(Path.Combine(other, "dotgit"), "decoy");
                var (worktree, _) = fixture.CreateLinkedWorktree(
                    main,
                    "linked3",
                    backLink: Path.Combine(other, "dotgit")
                );
                return (Path.Combine(worktree, "src"), mounts);
            }

            default:
            {
                var (worktree, _) = fixture.CreateLinkedWorktree(
                    main,
                    "native",
                    gitdirValue: Path.Combine(main, ".git", "worktrees", "native")
                );
                return (Path.Combine(worktree, "src"), mounts);
            }
        }
    }

    // A linked worktree whose gitdir is written through the cygdrive prefix: every
    // MSYS2 environment interprets it the same way, wherever the environment lives.
    private static (string Worktree, string Main) CreateCygdriveLinkedWorktree(MsysFixture fixture)
    {
        var main = fixture.CreateMainRepository("repo");
        var (worktree, _) = fixture.CreateLinkedWorktree(
            main,
            "linked",
            gitdirValue: MsysFixture.ToCygdrivePath(
                Path.Combine(main, ".git", "worktrees", "linked")
            )
        );

        return (worktree, main);
    }

    private static string CreateEnvironmentAt(MsysFixture fixture, string directory)
    {
        return fixture.CreateEnvironment(Path.GetRelativePath(fixture.Root, directory));
    }

    private static PosixMountTable LoadMounts(string environmentRoot)
    {
        var mounts = PosixMountTable.TryLoad(environmentRoot, out var problem);

        Assert.True(mounts is not null, problem);

        return mounts;
    }

    // Moves a directory away and leaves a junction to it in its place.
    private static string MoveBehindJunction(MsysFixture fixture, string directory)
    {
        var target = Path.Combine(fixture.Root, "moved-" + Path.GetFileName(directory));

        Directory.Move(directory, target);
        RunMklink("/J", directory, target);

        return directory;
    }

    [SupportedOSPlatform("windows")]
    private static void SetListDirectoryDenied(DirectoryInfo directory, bool denied)
    {
        var rule = new FileSystemAccessRule(
            WindowsIdentity.GetCurrent().User!,
            FileSystemRights.ListDirectory,
            AccessControlType.Deny
        );

        var security = directory.GetAccessControl();

        if (denied)
        {
            security.AddAccessRule(rule);
        }
        else
        {
            security.RemoveAccessRule(rule);
        }

        directory.SetAccessControl(security);
    }

    private static string ToLocalAdminSharePath(string path)
    {
        var fullPath = Path.GetFullPath(path);
        var root = Path.GetPathRoot(fullPath)!;

        return @"\\localhost\" + root[0] + @"$\" + fullPath[root.Length..];
    }

    // kind: "/H" for a file hard link, "/J" for a directory junction.
    private static void RunMklink(string kind, string link, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(link)!);

        using var process = Process.Start(
            new ProcessStartInfo("cmd.exe", ["/c", "mklink", kind, link, target])
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            }
        )!;

        process.WaitForExit();

        Assert.True(process.ExitCode == 0, $"mklink {kind} failed");
    }

    private static StringComparer PathComparer =>
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
}
