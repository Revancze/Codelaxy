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

    // CR-003, finding N-1: the observer caches each directory listing. An entry that
    // vanishes after its directory was listed (here by observing a sibling first) and
    // before File.GetAttributes gives a failed observation, not an exception and
    // not "missing". A fresh observer of the same tree sees the entry as missing.
    [Theory]
    [InlineData("b.txt", false, "b.txt")]
    [InlineData("dir", true, "dir")]
    [InlineData("dir", true, "dir/b.txt")]
    public void Observe_FailsWhenListedEntryVanishesBeforeItsAttributesAreRead(
        string vanishingName,
        bool vanishingIsDirectory,
        string observedPath
    )
    {
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            File.WriteAllText(Path.Combine(repositoryPath, "a.txt"), "sibling\n");

            var vanishingPath = Path.Combine(repositoryPath, vanishingName);

            if (vanishingIsDirectory)
            {
                Directory.CreateDirectory(vanishingPath);
                File.WriteAllText(Path.Combine(vanishingPath, "b.txt"), "inside\n");
            }
            else
            {
                File.WriteAllText(vanishingPath, "vanishing\n");
            }

            var observer = new WorkingTreeEntryObserver(repositoryPath, gitIgnoresCase: false);

            var sibling = observer.Observe("a.txt");

            Assert.True(sibling.Succeeded, sibling.Diagnostic);
            Assert.Equal(WorkingTreeEntryKind.RegularFile, sibling.Observation!.Kind);

            if (vanishingIsDirectory)
            {
                Directory.Delete(vanishingPath, recursive: true);
            }
            else
            {
                File.Delete(vanishingPath);
            }

            Assert.False(Path.Exists(vanishingPath));

            WorkingTreeEntryObservationResult? result = null;
            var exception = Record.Exception(() => result = observer.Observe(observedPath));

            Assert.Null(exception);
            Assert.NotNull(result);
            Assert.False(result.Succeeded);
            Assert.Null(result.Observation);
            Assert.StartsWith(
                $"Unable to observe working-tree path '{observedPath}': ",
                result.Diagnostic,
                StringComparison.Ordinal
            );

            // Positive control: without the stale listing the same path is missing.
            var fresh = new WorkingTreeEntryObserver(repositoryPath, gitIgnoresCase: false).Observe(
                observedPath
            );

            Assert.True(fresh.Succeeded, fresh.Diagnostic);
            Assert.Equal(WorkingTreeEntryKind.Missing, fresh.Observation!.Kind);
        }
        finally
        {
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
