using Codelaxy.Git;

namespace Codelaxy.Tests;

public class ProtectedRootDiscoveryTests
{
    [Fact]
    public void Discover_FindsOrdinaryRepository()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var source = Path.Combine(repository, "src");

        var result = ProtectedRootDiscovery.Discover(source);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);
        Assert.Contains(Path.GetFullPath(repository), result.Roots, PathComparer);
    }

    [Fact]
    public void Discover_FindsMainWorktreeThroughValidLinkedMetadata()
    {
        using var sandbox = new Sandbox();

        var main = sandbox.CreateRepository("main");
        var gitDirectory = Path.Combine(main, ".git", "worktrees", "feature");

        Directory.CreateDirectory(gitDirectory);
        File.WriteAllText(Path.Combine(gitDirectory, "commondir"), "../..\n");

        var linked = sandbox.CreateLinkedWorktree("feature", $"gitdir: {gitDirectory}\n");

        var result = ProtectedRootDiscovery.Discover(Path.Combine(linked, "src"));

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);
        Assert.Contains(Path.GetFullPath(linked), result.Roots, PathComparer);
        Assert.Contains(Path.GetFullPath(gitDirectory), result.Roots, PathComparer);
        Assert.Contains(Path.GetFullPath(main), result.Roots, PathComparer);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Discover_ReportsLockedLinkedMetadataAsIndeterminateOnWindows(bool lockCommondir)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var main = sandbox.CreateRepository("main");
        var gitDirectory = Path.Combine(main, ".git", "worktrees", "feature");

        Directory.CreateDirectory(gitDirectory);

        var commondir = Path.Combine(gitDirectory, "commondir");
        File.WriteAllText(commondir, "../..\n");

        var linked = sandbox.CreateLinkedWorktree("feature", $"gitdir: {gitDirectory}\n");

        var metadata = lockCommondir ? commondir : Path.Combine(linked, ".git");

        using var locked = new FileStream(
            metadata,
            FileMode.Open,
            FileAccess.ReadWrite,
            FileShare.None
        );

        var result = ProtectedRootDiscovery.Discover(Path.Combine(linked, "src"));

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    [Fact]
    public void Discover_DoesNotTreatInvalidGitdirAsComplete()
    {
        using var sandbox = new Sandbox();

        var linked = sandbox.CreateLinkedWorktree("feature", "gitdir: bad\0path\n");

        var result = ProtectedRootDiscovery.Discover(Path.Combine(linked, "src"));

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    [Fact]
    public void Discover_RejectsSymlinkedAncestor()
    {
        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var link = Path.Combine(sandbox.Root, "linked");

        Directory.CreateSymbolicLink(link, repository);

        var result = ProtectedRootDiscovery.Discover(Path.Combine(link, "src"));

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    [Theory]
    [InlineData(@"\\?\")]
    [InlineData(@"\\.\")]
    public void Discover_RecognizesWindowsDeviceAliases(string prefix)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var source = Path.Combine(repository, "src");
        var aliasedSource = prefix + Path.GetFullPath(source);

        Assert.True(Directory.Exists(aliasedSource));

        var result = ProtectedRootDiscovery.Discover(aliasedSource);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);

        AssertContainsRootIdentity(result.Roots, repository);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Discover_RecognizesLocalUncAliases(bool extended)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var sandbox = new Sandbox();

        var repository = sandbox.CreateRepository("repo");
        var source = Path.GetFullPath(Path.Combine(repository, "src"));

        var driveRoot = Path.GetPathRoot(source)!;
        var relativePath = source[driveRoot.Length..];

        var uncPrefix = extended ? @"\\?\UNC\localhost\" : @"\\localhost\";

        var aliasedSource = uncPrefix + driveRoot[0] + @"$\" + relativePath;

        Assert.True(Directory.Exists(aliasedSource));

        var result = ProtectedRootDiscovery.Discover(aliasedSource);

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);

        AssertContainsRootIdentity(result.Roots, repository);
    }

    private static void AssertContainsRootIdentity(IReadOnlyList<string> roots, string expectedRoot)
    {
        Assert.True(WindowsFileIdentity.TryRead(expectedRoot, out var expectedIdentity));

        Assert.Contains(
            roots,
            root =>
                WindowsFileIdentity.TryRead(root, out var actualIdentity)
                && actualIdentity == expectedIdentity
        );
    }

    [Fact]
    public void Discover_RejectsMissingCommondirInLinkedWorktree()
    {
        using var sandbox = new Sandbox();

        var main = sandbox.CreateRepository("main");

        var gitDirectory = Path.Combine(main, ".git", "worktrees", "feature");

        Directory.CreateDirectory(gitDirectory);

        // Deliberately missing commondir.
        var linked = sandbox.CreateLinkedWorktree("feature", $"gitdir: {gitDirectory}\n");

        var result = ProtectedRootDiscovery.Discover(Path.Combine(linked, "src"));

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    [Fact]
    public void Discover_AcceptsSeparateGitDirectoryWithoutCommondir()
    {
        using var sandbox = new Sandbox();

        var gitDirectory = Path.Combine(sandbox.Root, "separate-git-directory");

        Directory.CreateDirectory(gitDirectory);

        var worktree = sandbox.CreateLinkedWorktree("feature", $"gitdir: {gitDirectory}\n");

        var result = ProtectedRootDiscovery.Discover(Path.Combine(worktree, "src"));

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Complete, result.Status);

        Assert.Contains(Path.GetFullPath(worktree), result.Roots, PathComparer);

        Assert.Contains(Path.GetFullPath(gitDirectory), result.Roots, PathComparer);
    }

    [Fact]
    public void Discover_RejectsMissingCommondirInAlternateGitStorage()
    {
        using var sandbox = new Sandbox();

        var gitDirectory = Path.Combine(sandbox.Root, "git-storage", "worktrees", "feature");

        Directory.CreateDirectory(gitDirectory);

        var linked = sandbox.CreateLinkedWorktree("feature", $"gitdir: {gitDirectory}\n");

        var result = ProtectedRootDiscovery.Discover(Path.Combine(linked, "src"));

        Assert.Equal(ProtectedRootDiscovery.DiscoveryStatus.Indeterminate, result.Status);
    }

    private static StringComparer PathComparer =>
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    private sealed class Sandbox : IDisposable
    {
        public Sandbox()
        {
            Root = Path.Combine(Path.GetTempPath(), $"Codelaxy Discovery {Guid.NewGuid():N}");

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

        public void Dispose()
        {
            Directory.Delete(Root, recursive: true);
        }
    }
}
