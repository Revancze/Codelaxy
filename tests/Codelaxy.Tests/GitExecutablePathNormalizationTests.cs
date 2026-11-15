using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitExecutablePathNormalizationTests
{
    [Fact]
    public void ResolveDefaultGitExecutable_AcceptsQuotedAbsolutePathEntry()
    {
        using var sandbox = new Sandbox();
        var expectedGit = sandbox.CreateCandidate("trusted tools");
        var quotedDirectory = $"\"{Path.GetDirectoryName(expectedGit)}\"";

        var resolvedGit = GitProcessRunner.ResolveDefaultGitExecutable(
            quotedDirectory,
            sandbox.WorkingDirectory
        );

        Assert.Equal(expectedGit, resolvedGit);
    }

    [Fact]
    public void ResolveDefaultGitExecutable_KeepsQuotedCandidateOrderAfterRejectedEntries()
    {
        using var sandbox = new Sandbox();
        var repositoryGit = sandbox.CreateCandidate(Path.Combine("repo", "bin"));
        var expectedGit = sandbox.CreateCandidate("first trusted tools");
        var laterGit = sandbox.CreateCandidate("second trusted tools");
        var invalidDirectory = Path.Combine(sandbox.WorkingDirectory, "invalid\0directory");
        var pathVariable = string.Join(
            Path.PathSeparator,
            "\"relative tools\"",
            $"\"{invalidDirectory}\"",
            $"\"{Path.GetDirectoryName(repositoryGit)}\"",
            $"\"{Path.GetDirectoryName(expectedGit)}\"",
            $"\"{Path.GetDirectoryName(laterGit)}\""
        );

        var resolvedGit = GitProcessRunner.ResolveDefaultGitExecutable(
            pathVariable,
            sandbox.WorkingDirectory
        );

        Assert.Equal(expectedGit, resolvedGit);
    }

    private sealed class Sandbox : IDisposable
    {
        private readonly string _root = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy quoted PATH {Guid.NewGuid():N}"
        );

        public Sandbox()
        {
            WorkingDirectory = Path.Combine(_root, "repo");
            Directory.CreateDirectory(Path.Combine(WorkingDirectory, ".git"));
        }

        public string WorkingDirectory { get; }

        public string CreateCandidate(string directoryName)
        {
            var directory = Directory.CreateDirectory(Path.Combine(_root, directoryName));
            var fileName = OperatingSystem.IsWindows() ? "git.exe" : "git";
            var expectedGit = Path.GetFullPath(Path.Combine(directory.FullName, fileName));

            // Resolution checks file identity/location only. This inert file is never run.
            File.WriteAllText(expectedGit, "resolver fixture: do not execute");

            return expectedGit;
        }

        public void Dispose()
        {
            Directory.Delete(_root, recursive: true);
        }
    }
}
