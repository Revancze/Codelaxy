namespace Codelaxy.Git;

// Decides from the filesystem alone which directories may be controlled by a
// repository enclosing a given directory. Nothing is executed: Git cannot be
// asked, because Git is exactly what is being chosen.
internal static class RepositoryControlledPaths
{
    private const int MaxLinkDepth = 40;

    private static StringComparison PathComparison =>
        OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;

    internal enum DotGitObservation
    {
        Missing,
        File,
        Directory,
        Indeterminate,
    }

    // Every worktree enclosing the directory (nested repositories included), the
    // Git directories of linked worktrees and their main worktree, seen through
    // both the given path and its symlink-resolved physical path.
    public static IReadOnlyList<string> GetProtectedRoots(string directory)
    {
        var roots = new List<string>();

        var fullDirectory = Path.GetFullPath(directory);

        AddEnclosingWorktrees(fullDirectory, roots);

        var physicalDirectory = ResolvePhysicalPath(fullDirectory);

        if (!string.Equals(physicalDirectory, fullDirectory, PathComparison))
        {
            AddEnclosingWorktrees(physicalDirectory, roots);
        }

        return roots.Distinct(StringComparer.FromComparison(PathComparison)).ToArray();
    }

    // Classifies the .git entry without parsing its contents.
    // A missing parent or inaccessible entry is not proof of absence.
    internal static DotGitObservation ObserveDotGit(string directory)
    {
        try
        {
            var dotGit = Path.Combine(directory, ".git");
            var attributes = File.GetAttributes(dotGit);

            if ((attributes & FileAttributes.ReparsePoint) != FileAttributes.None)
            {
                return DotGitObservation.Indeterminate;
            }

            return (attributes & FileAttributes.Directory) != FileAttributes.None
                ? DotGitObservation.Directory
                : DotGitObservation.File;
        }
        catch (FileNotFoundException)
        {
            return DotGitObservation.Missing;
        }
        catch (Exception exception)
            when (exception
                    is IOException
                        or UnauthorizedAccessException
                        or System.Security.SecurityException
                        or ArgumentException
                        or NotSupportedException
            )
        {
            return DotGitObservation.Indeterminate;
        }
    }

    // True when the path, or what it finally resolves to, lies in a protected root.
    public static bool IsInsideAny(string path, IReadOnlyList<string> roots)
    {
        if (roots.Count == 0)
        {
            return false;
        }

        var fullPath = Path.GetFullPath(path);
        var physicalPath = ResolvePhysicalPath(fullPath);

        return roots.Any(root =>
            IsSameOrDescendant(fullPath, root) || IsSameOrDescendant(physicalPath, root)
        );
    }

    private static void AddEnclosingWorktrees(string startDirectory, List<string> roots)
    {
        for (var directory = startDirectory; directory is not null; )
        {
            var dotGit = Path.Combine(directory, ".git");

            if (Directory.Exists(dotGit))
            {
                AddRoot(directory, roots);
            }
            else if (File.Exists(dotGit))
            {
                AddRoot(directory, roots);
                AddLinkedRepositoryRoots(directory, dotGit, roots);
            }

            directory = Path.GetDirectoryName(directory);
        }
    }

    // A `.git` file points at the real Git directory ("gitdir: ..."). For a linked
    // worktree that directory names a common directory, whose parent is the main
    // worktree when the common directory is a `.git` directory.
    //
    // The metadata is untrusted input. Values that do not form a path are
    // ignored: the worktree itself is already protected by the caller.
    private static void AddLinkedRepositoryRoots(
        string worktree,
        string dotGitFile,
        List<string> roots
    )
    {
        try
        {
            AddLinkedRepositoryRootsCore(worktree, dotGitFile, roots);
        }
        catch (Exception exception)
            when (exception
                    is ArgumentException
                        or NotSupportedException
                        or IOException
                        or UnauthorizedAccessException
                        or System.Security.SecurityException
            )
        {
            // Roots added before the invalid value stay protected.
        }
    }

    private static void AddLinkedRepositoryRootsCore(
        string worktree,
        string dotGitFile,
        List<string> roots
    )
    {
        var gitDirectoryValue = ReadMetadataValue(dotGitFile, "gitdir: ");

        if (gitDirectoryValue is null)
        {
            return;
        }

        var gitDirectory = Path.GetFullPath(Path.Combine(worktree, gitDirectoryValue));

        AddRoot(gitDirectory, roots);

        var commonDirectoryValue = ReadMetadataValue(Path.Combine(gitDirectory, "commondir"), "");

        if (commonDirectoryValue is null)
        {
            return;
        }

        var commonDirectory = Path.GetFullPath(Path.Combine(gitDirectory, commonDirectoryValue));

        AddRoot(commonDirectory, roots);

        var trimmedCommonDirectory = Path.TrimEndingDirectorySeparator(commonDirectory);

        if (string.Equals(Path.GetFileName(trimmedCommonDirectory), ".git", PathComparison))
        {
            var mainWorktree = Path.GetDirectoryName(trimmedCommonDirectory);

            if (mainWorktree is not null)
            {
                AddRoot(mainWorktree, roots);
            }
        }
    }

    private static void AddRoot(string root, List<string> roots)
    {
        var fullRoot = Path.GetFullPath(root);

        roots.Add(fullRoot);
        roots.Add(ResolvePhysicalPath(fullRoot));
    }

    // Compatibility adapter for the existing root collector.
    // Security-sensitive discovery must inspect ReadStatus directly.
    private static string? ReadMetadataValue(string path, string prefix)
    {
        var observation = GitMetadataObservation.Read(path, prefix);

        return observation.Status == GitMetadataObservation.ReadStatus.Valid
            ? observation.Value
            : null;
    }

    // Resolves every symlink or junction along the path, segment by segment.
    // Unresolvable segments are kept as written; callers also check the given path.
    internal static string ResolvePhysicalPath(string path, int depth = 0)
    {
        var fullPath = Path.GetFullPath(path);
        var root = Path.GetPathRoot(fullPath);

        if (string.IsNullOrEmpty(root) || depth > MaxLinkDepth)
        {
            return fullPath;
        }

        var segments = fullPath[root.Length..]
            .Split(
                [Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
                StringSplitOptions.RemoveEmptyEntries
            );

        var current = root;

        foreach (var segment in segments)
        {
            var next = Path.Combine(current, segment);

            string? target = null;

            try
            {
                if (new FileInfo(next).LinkTarget is not null)
                {
                    target = File.ResolveLinkTarget(next, returnFinalTarget: true)?.FullName;
                }
            }
            catch (Exception exception)
                when (exception is IOException or UnauthorizedAccessException)
            {
                target = null;
            }

            current = target is null ? next : ResolvePhysicalPath(target, depth + 1);
        }

        return current;
    }

    private static bool IsSameOrDescendant(string path, string root)
    {
        var trimmedPath = Path.TrimEndingDirectorySeparator(path);
        var trimmedRoot = Path.TrimEndingDirectorySeparator(root);

        if (string.Equals(trimmedPath, trimmedRoot, PathComparison))
        {
            return true;
        }

        var prefix = Path.EndsInDirectorySeparator(trimmedRoot)
            ? trimmedRoot
            : trimmedRoot + Path.DirectorySeparatorChar;

        return trimmedPath.StartsWith(prefix, PathComparison);
    }
}
