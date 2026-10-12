using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitExecutableLocationVerifierTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Verify_DeniesRepositoryGitThroughUncAlias(bool extended)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteGit(Path.Combine(repository, "bin"));
        var alias = ToLocalAdminSharePath(fakeGit, extended);

        Assert.True(File.Exists(alias));

        var verdict = GitExecutableLocationVerifier.Verify(alias, Path.Combine(repository, "src"));

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, verdict);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Verify_AllowsExternalGitThroughLocalUncShare(bool extended)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        var externalGit = sandbox.WriteGit(Path.Combine(sandbox.Root, "external", "bin"));

        var alias = ToLocalAdminSharePath(externalGit, extended);

        Assert.True(File.Exists(alias));

        var verdict = GitExecutableLocationVerifier.Verify(alias, Path.Combine(repository, "src"));

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, verdict);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Verify_RejectsIncompleteLinkedMetadata(bool lockCommondir)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var main = sandbox.CreateRepository("main");
        var externalGit = sandbox.WriteGit(Path.Combine(sandbox.Root, "external", "bin"));

        var gitDirectory = Path.Combine(main, ".git", "worktrees", "feature");

        Directory.CreateDirectory(gitDirectory);

        var commondir = Path.Combine(gitDirectory, "commondir");
        File.WriteAllText(commondir, "../..\n");

        var linked = sandbox.CreateLinkedWorktree("feature", $"gitdir: {gitDirectory}\n");

        var lockedPath = lockCommondir ? commondir : Path.Combine(linked, ".git");

        using var locked = new FileStream(
            lockedPath,
            FileMode.Open,
            FileAccess.ReadWrite,
            FileShare.None
        );

        var verdict = GitExecutableLocationVerifier.Verify(
            externalGit,
            Path.Combine(linked, "src")
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, verdict);
    }

    [Theory]
    [InlineData(@"\\?\")]
    [InlineData(@"\\.\")]
    public void Verify_DeniesRepositoryGitThroughDeviceAlias(string prefix)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteGit(Path.Combine(repository, "bin"));

        var alias = prefix + Path.GetFullPath(fakeGit);

        Assert.True(File.Exists(alias));

        var verdict = GitExecutableLocationVerifier.Verify(alias, Path.Combine(repository, "src"));

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, verdict);
    }

    [Theory]
    [InlineData(@"\\?\")]
    [InlineData(@"\\.\")]
    public void Verify_DeniesGitWithAliasedWorkingDirectory(string prefix)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteGit(Path.Combine(repository, "bin"));

        var workingDirectory = prefix + Path.GetFullPath(Path.Combine(repository, "src"));

        Assert.True(Directory.Exists(workingDirectory));

        var verdict = GitExecutableLocationVerifier.Verify(fakeGit, workingDirectory);

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, verdict);
    }

    [Fact]
    public void Verify_RejectsMissingExecutable()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        var missingGit = Path.Combine(sandbox.Root, "external", "missing-git.exe");

        Assert.False(File.Exists(missingGit));

        var verdict = GitExecutableLocationVerifier.Verify(
            missingGit,
            Path.Combine(repository, "src")
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, verdict);
    }

    [Fact]
    public void Verify_RejectsDirectoryAsExecutable()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        var directory = Directory
            .CreateDirectory(Path.Combine(sandbox.Root, "external", "git.exe"))
            .FullName;

        var verdict = GitExecutableLocationVerifier.Verify(
            directory,
            Path.Combine(repository, "src")
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, verdict);
    }

    [Fact]
    public void Verify_AllowsCompleteRootlessLocalDiscovery()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var outside = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside")).FullName;

        var externalGit = sandbox.WriteGit(Path.Combine(sandbox.Root, "external", "bin"));

        var discovery = ProtectedRootDiscovery.Discover(outside);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, discovery.Status);

        Assert.Empty(discovery.Roots);

        var verdict = GitExecutableLocationVerifier.Verify(externalGit, outside);

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, verdict);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Verify_DeniesGitWithUncAliasedWorkingDirectory(bool extended)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var fakeGit = sandbox.WriteGit(Path.Combine(repository, "bin"));

        var workingDirectory = ToLocalAdminSharePath(Path.Combine(repository, "src"), extended);

        Assert.True(Directory.Exists(workingDirectory));

        var verdict = GitExecutableLocationVerifier.Verify(fakeGit, workingDirectory);

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, verdict);
    }

    [Fact]
    public void VerifyDetailed_DeniesKnownRootEvenWhenDiscoveryIsIncomplete()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var linked = sandbox.CreateLinkedWorktree("feature", "gitdir: bad\0path\n");

        var fakeGit = sandbox.WriteGit(Path.Combine(linked, "bin"));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            fakeGit,
            Path.Combine(linked, "src")
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Deny, decision.Verdict);
        Assert.Equal(GitExecutableLocationVerifier.Reason.InsideProtectedRoot, decision.Reason);
    }

    [Fact]
    public void VerifyDetailed_ExplainsCompleteRootlessAllow()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var outside = Directory.CreateDirectory(Path.Combine(sandbox.Root, "outside")).FullName;

        var externalGit = sandbox.WriteGit(Path.Combine(sandbox.Root, "external", "bin"));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(externalGit, outside);

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Allow, decision.Verdict);

        Assert.Equal(GitExecutableLocationVerifier.Reason.OutsideProtectedRoots, decision.Reason);
    }

    [Theory]
    [InlineData(@"\\remote.example\share\git.exe")]
    [InlineData(@"\\?\UNC\remote.example\share\git.exe")]
    public void VerifyDetailed_RejectsUnsupportedRemoteUncNamespace(string executable)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");

        var decision = GitExecutableLocationVerifier.VerifyDetailed(
            executable,
            Path.Combine(repository, "src")
        );

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);

        Assert.Equal(GitExecutableLocationVerifier.Reason.UnsupportedNamespace, decision.Reason);
    }

    [Fact]
    public void VerifyDetailed_RejectsMissingRootlessWorkingDirectory()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var externalGit = sandbox.WriteGit(Path.Combine(sandbox.Root, "external", "bin"));

        var missingDirectory = Path.Combine(sandbox.Root, "missing");

        Assert.False(Directory.Exists(missingDirectory));

        var decision = GitExecutableLocationVerifier.VerifyDetailed(externalGit, missingDirectory);

        Assert.Equal(GitExecutableLocationVerifier.Verdict.Indeterminate, decision.Verdict);

        Assert.Equal(GitExecutableLocationVerifier.Reason.IncompleteDiscovery, decision.Reason);
    }

    private static string ToLocalAdminSharePath(string path, bool extended)
    {
        var fullPath = Path.GetFullPath(path);
        var root = Path.GetPathRoot(fullPath)!;

        var prefix = extended ? @"\\?\UNC\localhost\" : @"\\localhost\";

        return prefix + root[0] + @"$\" + fullPath[root.Length..];
    }

    private sealed class Sandbox : IDisposable
    {
        public Sandbox()
        {
            Root = Path.Combine(Path.GetTempPath(), $"Codelaxy Verifier {Guid.NewGuid():N}");

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

        public string CreateLinkedWorktree(string name, string content)
        {
            var worktree = Path.Combine(Root, name);

            Directory.CreateDirectory(Path.Combine(worktree, "src"));
            File.WriteAllText(Path.Combine(worktree, ".git"), content);

            return worktree;
        }

        public string WriteGit(string directory)
        {
            Directory.CreateDirectory(directory);

            var executable = Path.Combine(directory, "git.exe");

            File.WriteAllText(executable, "test fixture");

            return executable;
        }

        public void Dispose()
        {
            Directory.Delete(Root, recursive: true);
        }
    }
}
