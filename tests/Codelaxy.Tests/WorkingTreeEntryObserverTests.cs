using Codelaxy.Git;

namespace Codelaxy.Tests;

public class WorkingTreeEntryObserverTests
{
    [Fact]
    public void Observe_DoesNotTraverseSymbolicLinkAncestorOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var repositoryPath = CreateTemporaryDirectory();
        var externalPath = CreateTemporaryDirectory();

        var linkPath = Path.Combine(repositoryPath, "dir");

        try
        {
            File.WriteAllText(Path.Combine(externalPath, "file.txt"), "outside repository\n");

            Directory.CreateSymbolicLink(linkPath, externalPath);

            var observer = new WorkingTreeEntryObserver(repositoryPath, gitIgnoresCase: false);

            var result = observer.Observe("dir/file.txt");

            Assert.True(result.Succeeded, result.Diagnostic);

            var observation = Assert.IsType<WorkingTreeEntryObservation>(result.Observation);

            Assert.Equal(WorkingTreeEntryKind.Missing, observation.Kind);
        }
        finally
        {
            if (Directory.Exists(linkPath) || File.Exists(linkPath))
            {
                new DirectoryInfo(linkPath).Delete();
            }

            DeleteDirectory(repositoryPath);
            DeleteDirectory(externalPath);
        }
    }

    [Fact]
    public void Observe_PreservesBackslashInGitPathOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var path = Path.Combine(repositoryPath, @"a\b.txt");

            File.WriteAllText(path, "content\n");

            var observer = new WorkingTreeEntryObserver(repositoryPath, gitIgnoresCase: false);

            var result = observer.Observe(@"a\b.txt");

            Assert.True(result.Succeeded, result.Diagnostic);

            var observation = Assert.IsType<WorkingTreeEntryObservation>(result.Observation);

            Assert.Equal(WorkingTreeEntryKind.RegularFile, observation.Kind);

            Assert.Equal("100644", observation.Mode);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public void Observe_ReturnsDiagnosticWhenDirectoryCannotBeEnumeratedOnLinux()
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        var repositoryPath = CreateTemporaryDirectory();

        var blockedPath = Path.Combine(repositoryPath, "blocked");

        try
        {
            Directory.CreateDirectory(blockedPath);

            File.SetUnixFileMode(blockedPath, UnixFileMode.None);

            var observer = new WorkingTreeEntryObserver(repositoryPath, gitIgnoresCase: false);

            var result = observer.Observe("blocked/file.txt");

            Assert.False(result.Succeeded);

            Assert.Null(result.Observation);

            Assert.NotEmpty(result.Diagnostic);
        }
        finally
        {
            if (Directory.Exists(blockedPath))
            {
                File.SetUnixFileMode(
                    blockedPath,
                    UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
                );
            }

            DeleteDirectory(repositoryPath);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy Working Tree Observer Tests {Guid.NewGuid():N}"
        );

        Directory.CreateDirectory(path);

        return path;
    }

    private static void DeleteDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
        {
            File.SetAttributes(file, FileAttributes.Normal);
        }

        foreach (
            var directory in Directory.EnumerateDirectories(path, "*", SearchOption.AllDirectories)
        )
        {
            File.SetAttributes(directory, FileAttributes.Normal);
        }

        File.SetAttributes(path, FileAttributes.Normal);

        Directory.Delete(path, recursive: true);
    }
}
