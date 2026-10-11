namespace Codelaxy.Git;

// Strict observation of repository-controlled roots.
// No result from this class alone authorizes execution.
internal static class ProtectedRootDiscovery
{
    internal enum DiscoveryStatus
    {
        Complete,
        Indeterminate,
    }

    internal sealed record Result(DiscoveryStatus Status, IReadOnlyList<string> Roots);

    internal static Result Discover(string directory)
    {
        var roots = new HashSet<string>(
            OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal
        );

        try
        {
            for (
                var ancestor = Path.GetFullPath(directory);
                ancestor is not null;
                ancestor = Path.GetDirectoryName(ancestor)
            )
            {
                if (!IsObservableDirectory(ancestor) || !TryCollectWorktree(ancestor, roots))
                {
                    return new Result(DiscoveryStatus.Indeterminate, roots.ToArray());
                }
            }

            return new Result(DiscoveryStatus.Complete, roots.ToArray());
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
            return new Result(DiscoveryStatus.Indeterminate, roots.ToArray());
        }
    }

    private static bool TryCollectWorktree(string directory, HashSet<string> roots)
    {
        switch (RepositoryControlledPaths.ObserveDotGit(directory))
        {
            case RepositoryControlledPaths.DotGitObservation.Missing:
                return true;

            case RepositoryControlledPaths.DotGitObservation.Directory:
                roots.Add(directory);
                return true;

            case RepositoryControlledPaths.DotGitObservation.File:
                roots.Add(directory);
                return TryCollectLinkedRoots(directory, roots);

            default:
                return false;
        }
    }

    private static bool TryCollectLinkedRoots(string worktree, HashSet<string> roots)
    {
        var gitdir = GitMetadataObservation.Read(Path.Combine(worktree, ".git"), "gitdir: ");

        if (
            gitdir.Status != GitMetadataObservation.ReadStatus.Valid
            || gitdir.Value is null
            || !TryAddRoot(worktree, gitdir.Value, roots, out var gitDirectory)
        )
        {
            return false;
        }

        var commondir = GitMetadataObservation.Read(Path.Combine(gitDirectory, "commondir"), "");

        if (commondir.Status == GitMetadataObservation.ReadStatus.Missing)
        {
            return !IsLinkedWorktreeGitDirectory(gitDirectory);
        }

        if (
            commondir.Status != GitMetadataObservation.ReadStatus.Valid
            || commondir.Value is null
            || !TryAddRoot(gitDirectory, commondir.Value, roots, out var commonDirectory)
        )
        {
            return false;
        }

        return TryCollectMainWorktree(commonDirectory, roots);
    }

    private static bool IsLinkedWorktreeGitDirectory(string gitDirectory)
    {
        var parent = Path.GetDirectoryName(Path.TrimEndingDirectorySeparator(gitDirectory));

        if (parent is null)
        {
            return false;
        }

        var comparison = OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;

        return string.Equals(Path.GetFileName(parent), "worktrees", comparison);
    }

    private static bool TryCollectMainWorktree(string commonDirectory, HashSet<string> roots)
    {
        var trimmed = Path.TrimEndingDirectorySeparator(commonDirectory);

        var comparison = OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;

        if (!string.Equals(Path.GetFileName(trimmed), ".git", comparison))
        {
            return true;
        }

        var mainWorktree = Path.GetDirectoryName(trimmed);

        return mainWorktree is not null && TryAddRoot(mainWorktree, ".", roots, out _);
    }

    private static bool TryAddRoot(
        string baseDirectory,
        string value,
        HashSet<string> roots,
        out string resolved
    )
    {
        resolved = Path.GetFullPath(Path.Combine(baseDirectory, value));

        if (!HasObservableAncestors(resolved))
        {
            return false;
        }

        roots.Add(resolved);
        return true;
    }

    private static bool HasObservableAncestors(string directory)
    {
        for (
            var ancestor = directory;
            ancestor is not null;
            ancestor = Path.GetDirectoryName(ancestor)
        )
        {
            if (!IsObservableDirectory(ancestor))
            {
                return false;
            }
        }

        return true;
    }

    private static bool IsObservableDirectory(string directory)
    {
        var attributes = File.GetAttributes(directory);

        return (attributes & FileAttributes.Directory) != FileAttributes.None
            && (attributes & FileAttributes.ReparsePoint) == FileAttributes.None;
    }
}
