namespace Codelaxy.Git;

// Compares one candidate with one protected root.
// NoMatch is NOT permission to execute.
internal static class WindowsProtectedAncestorMatcher
{
    internal enum MatchResult
    {
        Match,
        NoMatch,
        Indeterminate,
    }

    internal static MatchResult Check(string candidatePath, string protectedRoot)
    {
        if (
            !OperatingSystem.IsWindows()
            || string.IsNullOrWhiteSpace(candidatePath)
            || string.IsNullOrWhiteSpace(protectedRoot)
        )
        {
            return MatchResult.Indeterminate;
        }

        try
        {
            if (!WindowsFileIdentity.TryRead(protectedRoot, out var rootIdentity))
            {
                return MatchResult.Indeterminate;
            }

            return CheckAncestors(Path.GetFullPath(candidatePath), rootIdentity);
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
            return MatchResult.Indeterminate;
        }
    }

    private static MatchResult CheckAncestors(
        string current,
        WindowsFileIdentity.Identity rootIdentity
    )
    {
        while (true)
        {
            // Lexical ancestry is unreliable across reparse points.
            var attributes = File.GetAttributes(current);

            if ((attributes & FileAttributes.ReparsePoint) != FileAttributes.None)
            {
                return MatchResult.Indeterminate;
            }

            if (!WindowsFileIdentity.TryRead(current, out var identity))
            {
                return MatchResult.Indeterminate;
            }

            if (identity == rootIdentity)
            {
                return MatchResult.Match;
            }

            var parent = Path.GetDirectoryName(current);

            if (parent is null)
            {
                return MatchResult.NoMatch;
            }

            if (string.Equals(parent, current, StringComparison.OrdinalIgnoreCase))
            {
                return MatchResult.Indeterminate;
            }

            current = parent;
        }
    }
}
