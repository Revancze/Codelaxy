using System.Diagnostics;
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
            mkfifo.WaitForExit();
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
                // Release a reader blocked in open(2).
                using var writer = new FileStream(fifo, FileMode.Open, FileAccess.Write);
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
            string.Format(dotGitTemplate, gitDirectory)
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

    private static StringComparer PathComparer =>
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

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

        public string CreateFileSymlink(string link, string target)
        {
            File.CreateSymbolicLink(link, target);
            _links.Add(link);

            return link;
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
