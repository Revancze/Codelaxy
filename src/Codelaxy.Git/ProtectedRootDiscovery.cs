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

    // Whether the result depends on POSIX paths in Git metadata: Proven ones were
    // interpreted through the configured environment, Unresolved ones were not.
    internal enum PosixMetadataUse
    {
        None,
        Proven,
        Unresolved,
    }

    internal sealed record Result(
        DiscoveryStatus Status,
        IReadOnlyList<string> Roots,
        PosixMetadataUse PosixMetadata
    );

    internal static Result Discover(string directory)
    {
        return Discover(directory, mounts: null);
    }

    // mounts: the explicitly configured MSYS2/Cygwin environment, or null. Without it,
    // POSIX paths in Git metadata stay unresolved and the result is Indeterminate.
    internal static Result Discover(string directory, PosixMountTable? mounts)
    {
        var roots = new HashSet<string>(
            OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal
        );

        var posixMetadata = PosixMetadataUse.None;

        try
        {
            for (
                var ancestor = Path.GetFullPath(directory);
                ancestor is not null;
                ancestor = Path.GetDirectoryName(ancestor)
            )
            {
                if (
                    !IsObservableDirectory(ancestor)
                    || !TryCollectWorktree(ancestor, roots, mounts, ref posixMetadata)
                )
                {
                    return new Result(
                        DiscoveryStatus.Indeterminate,
                        roots.ToArray(),
                        posixMetadata
                    );
                }
            }

            return new Result(DiscoveryStatus.Complete, roots.ToArray(), posixMetadata);
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
            return new Result(DiscoveryStatus.Indeterminate, roots.ToArray(), posixMetadata);
        }
    }

    private static bool TryCollectWorktree(
        string directory,
        HashSet<string> roots,
        PosixMountTable? mounts,
        ref PosixMetadataUse posixMetadata
    )
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
                return TryCollectLinkedRoots(directory, roots, mounts, ref posixMetadata);

            default:
                return false;
        }
    }

    private static bool TryCollectLinkedRoots(
        string worktree,
        HashSet<string> roots,
        PosixMountTable? mounts,
        ref PosixMetadataUse posixMetadata
    )
    {
        var gitdir = GitMetadataObservation.Read(Path.Combine(worktree, ".git"), "gitdir: ");

        if (gitdir.Status != GitMetadataObservation.ReadStatus.Valid || gitdir.Value is null)
        {
            return false;
        }

        if (IsWindowsPosixPath(gitdir.Value))
        {
            // Unresolved until proven, also when the proof throws.
            posixMetadata = PosixMetadataUse.Unresolved;

            if (
                mounts is null
                || !TryCollectPosixLinkedRoots(worktree, gitdir.Value, mounts, roots)
            )
            {
                return false;
            }

            posixMetadata = PosixMetadataUse.Proven;
            return true;
        }

        if (!TryAddRoot(worktree, gitdir.Value, roots, out var gitDirectory))
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

    // On Windows, "/x/..." is neither a Windows path nor relative: MSYS2/Cygwin Git
    // wrote it. "//server/share" stays a native UNC path.
    private static bool IsWindowsPosixPath(string value)
    {
        return OperatingSystem.IsWindows()
            && value.Length > 0
            && value[0] == '/'
            && (value.Length == 1 || value[1] != '/');
    }

    // A translated POSIX gitdir is accepted only when the metadata proves it:
    // its back-link names this worktree's .git file (by file identity), it sits in
    // <common>\worktrees\<id> with <id> from the POSIX value, and commondir names
    // that same <common>. Any doubt leaves the discovery Indeterminate.
    private static bool TryCollectPosixLinkedRoots(
        string worktree,
        string value,
        PosixMountTable mounts,
        HashSet<string> roots
    )
    {
        var gitDirectory = mounts.Map(value);

        if (
            gitDirectory is null
            || !Directory.Exists(gitDirectory)
            || !HasObservableAncestors(gitDirectory)
            || !IsLinkedWorktreeGitDirectory(gitDirectory)
            || !string.Equals(
                Path.GetFileName(Path.TrimEndingDirectorySeparator(gitDirectory)),
                GetLastPosixSegment(value),
                StringComparison.OrdinalIgnoreCase
            )
            || !IsBackLinkTo(gitDirectory, Path.Combine(worktree, ".git"), mounts)
        )
        {
            return false;
        }

        var expectedCommonDirectory = Path.GetDirectoryName(
            Path.GetDirectoryName(Path.TrimEndingDirectorySeparator(gitDirectory))
        );

        var commondir = GitMetadataObservation.Read(Path.Combine(gitDirectory, "commondir"), "");

        if (
            expectedCommonDirectory is null
            || commondir.Status != GitMetadataObservation.ReadStatus.Valid
            || commondir.Value is null
        )
        {
            return false;
        }

        var commonDirectory = ResolveMetadataPath(gitDirectory, commondir.Value, mounts);

        if (
            commonDirectory is null
            || !Directory.Exists(commonDirectory)
            || !HasObservableAncestors(commonDirectory)
            || !IsSameFile(commonDirectory, expectedCommonDirectory)
        )
        {
            return false;
        }

        roots.Add(gitDirectory);
        roots.Add(commonDirectory);

        return TryCollectMainWorktree(commonDirectory, roots);
    }

    private static string GetLastPosixSegment(string value)
    {
        var trimmed = value.TrimEnd('/');

        return trimmed[(trimmed.LastIndexOf('/') + 1)..];
    }

    private static bool IsBackLinkTo(string gitDirectory, string dotGitFile, PosixMountTable mounts)
    {
        var backLink = GitMetadataObservation.Read(Path.Combine(gitDirectory, "gitdir"), "");

        if (backLink.Status != GitMetadataObservation.ReadStatus.Valid || backLink.Value is null)
        {
            return false;
        }

        // Git writes the back-link as an absolute path; a relative one is not proof.
        if (!IsWindowsPosixPath(backLink.Value) && !Path.IsPathFullyQualified(backLink.Value))
        {
            return false;
        }

        var target = IsWindowsPosixPath(backLink.Value)
            ? mounts.Map(backLink.Value)
            : Path.GetFullPath(backLink.Value);

        return target is not null && IsSameFile(target, dotGitFile);
    }

    private static string? ResolveMetadataPath(
        string baseDirectory,
        string value,
        PosixMountTable mounts
    )
    {
        return IsWindowsPosixPath(value)
            ? mounts.Map(value)
            : Path.GetFullPath(Path.Combine(baseDirectory, value));
    }

    private static bool IsSameFile(string left, string right)
    {
        return WindowsFileIdentity.TryRead(left, out var leftIdentity)
            && WindowsFileIdentity.TryRead(right, out var rightIdentity)
            && leftIdentity == rightIdentity;
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
