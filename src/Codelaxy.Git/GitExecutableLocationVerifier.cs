using System.Runtime.InteropServices;

namespace Codelaxy.Git;

// Evaluates executable location only.
// It does not authorize process creation on its own.
internal static class GitExecutableLocationVerifier
{
    internal enum Verdict
    {
        Allow,
        Deny,
        Indeterminate,
    }

    internal enum Reason
    {
        OutsideProtectedRoots,
        InsideProtectedRoot,
        IncompleteDiscovery,
        UnverifiableLocation,
        UnsupportedNamespace,
        UnsupportedPlatform,
    }

    [StructLayout(LayoutKind.Sequential)]
    internal readonly record struct Decision(Verdict Verdict, Reason Reason);

    internal static Verdict Verify(string executable, string workingDirectory)
    {
        return VerifyDetailed(executable, workingDirectory).Verdict;
    }

    internal static Decision VerifyDetailed(string executable, string workingDirectory)
    {
        if (!OperatingSystem.IsWindows())
        {
            return new(Verdict.Indeterminate, Reason.UnsupportedPlatform);
        }

        if (string.IsNullOrWhiteSpace(executable) || string.IsNullOrWhiteSpace(workingDirectory))
        {
            return new(Verdict.Indeterminate, Reason.UnverifiableLocation);
        }

        try
        {
            if (
                !Path.IsPathFullyQualified(executable)
                || !Path.IsPathFullyQualified(workingDirectory)
            )
            {
                return new(Verdict.Indeterminate, Reason.UnverifiableLocation);
            }

            return VerifyWindows(executable, workingDirectory);
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
            return new(Verdict.Indeterminate, Reason.UnverifiableLocation);
        }
    }

    private static Decision VerifyWindows(string executable, string workingDirectory)
    {
        if (!TryGetLocalEquivalent(executable, out var localEquivalent))
        {
            return new(Verdict.Indeterminate, Reason.UnsupportedNamespace);
        }

        var discovery = ProtectedRootDiscovery.Discover(workingDirectory);
        var unverifiable = false;

        foreach (var root in discovery.Roots)
        {
            switch (WindowsProtectedAncestorMatcher.Check(executable, root))
            {
                case WindowsProtectedAncestorMatcher.MatchResult.Match:
                    return new(Verdict.Deny, Reason.InsideProtectedRoot);

                case WindowsProtectedAncestorMatcher.MatchResult.Indeterminate:
                    unverifiable = true;
                    break;
            }
        }

        if (
            discovery.Status != ProtectedRootDiscovery.DiscoveryStatus.Complete
            || discovery.Roots.Count == 0
        )
        {
            return new(Verdict.Indeterminate, Reason.IncompleteDiscovery);
        }

        if (unverifiable)
        {
            return new(Verdict.Indeterminate, Reason.UnverifiableLocation);
        }

        if (!IsObservableExecutable(executable))
        {
            return new(Verdict.Indeterminate, Reason.UnverifiableLocation);
        }

        if (
            localEquivalent is not null
            && (
                !WindowsFileIdentity.TryRead(executable, out var actual)
                || !WindowsFileIdentity.TryRead(localEquivalent, out var expected)
                || actual != expected
            )
        )
        {
            return new(Verdict.Indeterminate, Reason.UnverifiableLocation);
        }

        return new(Verdict.Allow, Reason.OutsideProtectedRoots);
    }

    private static bool TryGetLocalEquivalent(string path, out string? localEquivalent)
    {
        localEquivalent = null;

        if (IsDrivePath(path))
        {
            return IsLocalDrive(path);
        }

        if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            path = @"\\" + path[8..];
        }

        if (path.StartsWith(@"\\localhost\", StringComparison.OrdinalIgnoreCase))
        {
            var relative = path[@"\\localhost\".Length..];

            if (
                relative.Length < 3
                || !char.IsLetter(relative[0])
                || relative[1] != '$'
                || relative[2] != '\\'
            )
            {
                return false;
            }

            localEquivalent = char.ToUpperInvariant(relative[0]) + ":" + relative[2..];
            return IsLocalDrive(localEquivalent);
        }

        if (
            path.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase)
            || path.StartsWith(@"\\.\", StringComparison.OrdinalIgnoreCase)
        )
        {
            localEquivalent = path[4..];
            return IsDrivePath(localEquivalent) && IsLocalDrive(localEquivalent);
        }

        return false;
    }

    private static bool IsDrivePath(string path)
    {
        return path.Length >= 3 && char.IsLetter(path[0]) && path[1] == ':' && path[2] == '\\';
    }

    private static bool IsLocalDrive(string path)
    {
        var driveType = new DriveInfo(path[..3]).DriveType;

        return driveType is DriveType.Fixed or DriveType.Removable;
    }

    private static bool IsObservableExecutable(string executable)
    {
        var current = Path.GetFullPath(executable);
        var isExecutable = true;

        while (current is not null)
        {
            var attributes = File.GetAttributes(current);

            if (
                (attributes & FileAttributes.ReparsePoint) != FileAttributes.None
                || !WindowsFileIdentity.TryRead(current, out _)
            )
            {
                return false;
            }

            if (isExecutable && (attributes & FileAttributes.Directory) != FileAttributes.None)
            {
                return false;
            }

            isExecutable = false;
            current = Path.GetDirectoryName(current);
        }

        return true;
    }
}
