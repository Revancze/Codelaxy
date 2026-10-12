using System.Globalization;

namespace Codelaxy.Git;

// Interprets POSIX paths written by MSYS2/Cygwin Git through the mount table of an
// explicitly configured environment root. Nothing is executed. A mapped path is a
// hypothesis only; ProtectedRootDiscovery must still prove it against the metadata.
internal sealed class PosixMountTable
{
    private const long MaxFstabLength = 64 * 1024;

    private static readonly HashSet<string> AllowedOptions = new(StringComparer.Ordinal)
    {
        "binary",
        "posix=0",
        "noacl",
        "user",
    };

    private readonly string _cygdrivePrefix;
    private readonly IReadOnlyList<(string MountPoint, string Target)> _mounts;

    private PosixMountTable(
        string root,
        string cygdrivePrefix,
        IReadOnlyList<(string MountPoint, string Target)> mounts
    )
    {
        Root = root;
        _cygdrivePrefix = cygdrivePrefix;
        _mounts = mounts;
    }

    internal string Root { get; }

    internal static PosixMountTable? TryLoad(string environmentRoot)
    {
        return TryLoad(environmentRoot, out _);
    }

    // Accepts only a local MSYS2 layout whose mount table can be read completely:
    // a drive path on a local drive, <root>\usr\bin\msys-2.0.dll, <root>\etc\fstab,
    // a missing or empty plain <root>\etc\fstab.d, and no reparse point on the way to
    // the root or below it.
    // Anything else returns null and says why.
    internal static PosixMountTable? TryLoad(string environmentRoot, out string problem)
    {
        ArgumentNullException.ThrowIfNull(environmentRoot);

        if (!OperatingSystem.IsWindows())
        {
            problem = "MSYS2 environments are supported only on Windows";
            return null;
        }

        try
        {
            if (
                !Path.IsPathFullyQualified(environmentRoot)
                || !GitExecutableLocationVerifier.IsLocalDrivePath(
                    Path.GetFullPath(environmentRoot)
                )
            )
            {
                problem = @"expected a fully qualified path on a local drive, such as C:\msys64";
                return null;
            }

            var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(environmentRoot));
            var fstab = Path.Combine(root, "etc", "fstab");
            var layoutProblem = GetLayoutProblem(root, fstab);

            if (layoutProblem is not null)
            {
                problem = layoutProblem;
                return null;
            }

            return Parse(root, fstab, out problem);
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
            problem = $"the environment cannot be read ({exception.Message})";
            return null;
        }
    }

    // True only for this environment's own <root>\usr\bin\git.exe, compared by file
    // identity of both the executable and its directory, never by path text. The
    // directory matters because a hard link elsewhere would load another runtime.
    internal bool IsEnvironmentGit(string executable)
    {
        var binDirectory = Path.Combine(Root, "usr", "bin");
        var executableDirectory = Path.GetDirectoryName(Path.GetFullPath(executable));

        return executableDirectory is not null
            && IsSameFile(executable, Path.Combine(binDirectory, "git.exe"))
            && IsSameFile(executableDirectory, binDirectory);
    }

    // One Windows path for an absolute POSIX path, or null when it cannot be mapped.
    // Precedence: explicit mounts (longest first), then the cygdrive prefix, then root.
    internal string? Map(string posixPath)
    {
        if (
            posixPath.Length == 0
            || posixPath[0] != '/'
            || posixPath.StartsWith("//", StringComparison.Ordinal)
            || posixPath.Contains('\0', StringComparison.Ordinal)
            || posixPath.Contains('\\', StringComparison.Ordinal)
        )
        {
            return null;
        }

        var segments = posixPath.Split('/', StringSplitOptions.RemoveEmptyEntries);

        if (segments.Any(segment => segment is "." or ".."))
        {
            return null;
        }

        var normalized = "/" + string.Join('/', segments);

        foreach (var (mountPoint, target) in _mounts.OrderByDescending(m => m.MountPoint.Length))
        {
            if (
                string.Equals(normalized, mountPoint, StringComparison.Ordinal)
                || normalized.StartsWith(mountPoint + "/", StringComparison.Ordinal)
            )
            {
                return Combine(target, normalized[mountPoint.Length..]);
            }
        }

        var drive = TryMapCygdrive(normalized);

        return drive ?? Combine(Root, normalized);
    }

    private string? TryMapCygdrive(string normalized)
    {
        string remainder;

        if (string.Equals(_cygdrivePrefix, "/", StringComparison.Ordinal))
        {
            remainder = normalized;
        }
        else if (normalized.StartsWith(_cygdrivePrefix + "/", StringComparison.Ordinal))
        {
            remainder = normalized[_cygdrivePrefix.Length..];
        }
        else
        {
            return null;
        }

        var segments = remainder.Split('/', StringSplitOptions.RemoveEmptyEntries);

        if (segments.Length == 0 || segments[0].Length != 1 || !char.IsAsciiLetter(segments[0][0]))
        {
            return null;
        }

        return Path.GetFullPath(
            char.ToUpperInvariant(segments[0][0]) + @":\" + string.Join('\\', segments[1..])
        );
    }

    private static string Combine(string target, string rest)
    {
        return Path.GetFullPath(target + rest.Replace('/', '\\'));
    }

    private static string? GetLayoutProblem(string root, string fstab)
    {
        var runtime = Path.Combine(root, "usr", "bin", "msys-2.0.dll");
        var fstabDirectory = Path.Combine(root, "etc", "fstab.d");

        if (!IsPlainDirectoryChain(root))
        {
            return $"'{root}' or one of its parents is missing, not a directory, or a link";
        }

        if (!IsPlainFileBelow(root, runtime))
        {
            return $"'{runtime}' is missing, not a regular file, or reached through a link";
        }

        if (!IsPlainFileBelow(root, fstab))
        {
            return $"'{fstab}' is missing, not a regular file, or reached through a link";
        }

        if (new FileInfo(fstab).Length > MaxFstabLength)
        {
            return $"'{fstab}' is larger than 64 KB";
        }

        return GetFstabDirectoryProblem(fstabDirectory);
    }

    // etc\fstab.d may be missing. When present it must be a plain directory without
    // entries: a file or a link there is not "no further mount tables", and one that
    // cannot be listed throws and refuses the environment.
    private static string? GetFstabDirectoryProblem(string fstabDirectory)
    {
        if (!TryGetAttributes(fstabDirectory, out var entry))
        {
            return null;
        }

        if (
            (entry & FileAttributes.Directory) == FileAttributes.None
            || (entry & FileAttributes.ReparsePoint) != FileAttributes.None
        )
        {
            return $"'{fstabDirectory}' is not a plain directory";
        }

        return Directory.EnumerateFileSystemEntries(fstabDirectory).Any()
            ? $"'{fstabDirectory}' is not empty"
            : null;
    }

    private static PosixMountTable? Parse(string root, string fstab, out string problem)
    {
        var lines = File.ReadAllLines(fstab);
        var cygdrivePrefix = (string?)null;
        var mounts = new List<(string MountPoint, string Target)>();

        for (var index = 0; index < lines.Length; index++)
        {
            var trimmed = lines[index].Trim();

            if (trimmed.Length == 0 || trimmed[0] == '#')
            {
                continue;
            }

            var fields = trimmed.Split([' ', '\t'], StringSplitOptions.RemoveEmptyEntries);

            if (!TryParseEntry(fields, mounts, ref cygdrivePrefix))
            {
                problem = string.Create(
                    CultureInfo.InvariantCulture,
                    $"'{fstab}' line {index + 1} is not supported: {trimmed}"
                );
                return null;
            }
        }

        if (
            mounts.Any(mount => mount.MountPoint == "/")
            || mounts.Select(mount => mount.MountPoint).Distinct(StringComparer.Ordinal).Count()
                != mounts.Count
        )
        {
            problem = $"'{fstab}' mounts '/' or repeats a mount point";
            return null;
        }

        problem = string.Empty;
        return new PosixMountTable(root, cygdrivePrefix ?? "/cygdrive", mounts);
    }

    private static bool TryParseEntry(
        string[] fields,
        List<(string MountPoint, string Target)> mounts,
        ref string? cygdrivePrefix
    )
    {
        if (
            fields.Length != 6
            || fields[4] != "0"
            || fields[5] != "0"
            || !fields[3].Split(',').All(AllowedOptions.Contains)
            || !TryNormalizeMountPoint(fields[1], out var mountPoint)
        )
        {
            return false;
        }

        switch (fields[2])
        {
            case "cygdrive" when fields[0] == "none" && cygdrivePrefix is null:
                cygdrivePrefix = mountPoint;
                return true;

            case "usertemp" when fields[0] == "none":
                mounts.Add((mountPoint, Path.TrimEndingDirectorySeparator(Path.GetTempPath())));
                return true;

            case "ntfs" when TryNormalizeWindowsTarget(fields[0], out var target):
                mounts.Add((mountPoint, target));
                return true;

            default:
                return false;
        }
    }

    private static bool TryNormalizeMountPoint(string value, out string mountPoint)
    {
        mountPoint = string.Empty;

        if (value.Length == 0 || value[0] != '/' || value.Contains('\\', StringComparison.Ordinal))
        {
            return false;
        }

        var segments = value.Split('/', StringSplitOptions.RemoveEmptyEntries);

        if (segments.Any(segment => segment is "." or ".."))
        {
            return false;
        }

        mountPoint = "/" + string.Join('/', segments);
        return true;
    }

    private static bool TryNormalizeWindowsTarget(string value, out string target)
    {
        target = string.Empty;

        // fstab octal escapes (\040) are not supported.
        if (value.Contains('\\', StringComparison.Ordinal))
        {
            return false;
        }

        var candidate = value.Replace('/', '\\');

        if (
            !Path.IsPathFullyQualified(candidate)
            || candidate.StartsWith(@"\\", StringComparison.Ordinal)
        )
        {
            return false;
        }

        target = Path.TrimEndingDirectorySeparator(Path.GetFullPath(candidate));
        return true;
    }

    private static bool IsPlainDirectoryChain(string directory)
    {
        for (var current = directory; current is not null; current = Path.GetDirectoryName(current))
        {
            if (!IsPlainDirectory(current))
            {
                return false;
            }
        }

        return true;
    }

    // Windows reports a file behind a junctioned parent as a regular file, so every
    // directory between the (already checked) root and the file is checked as well.
    private static bool IsPlainFileBelow(string root, string file)
    {
        for (
            var current = Path.GetDirectoryName(file);
            !string.Equals(current, root, StringComparison.OrdinalIgnoreCase);
            current = Path.GetDirectoryName(current)
        )
        {
            if (current is null || !IsPlainDirectory(current))
            {
                return false;
            }
        }

        return IsPlainFile(file);
    }

    private static bool IsPlainDirectory(string path)
    {
        return TryGetAttributes(path, out var attributes)
            && (attributes & FileAttributes.Directory) != FileAttributes.None
            && (attributes & FileAttributes.ReparsePoint) == FileAttributes.None;
    }

    private static bool IsPlainFile(string path)
    {
        return TryGetAttributes(path, out var attributes)
            && (attributes & FileAttributes.Directory) == FileAttributes.None
            && (attributes & FileAttributes.ReparsePoint) == FileAttributes.None;
    }

    private static bool TryGetAttributes(string path, out FileAttributes attributes)
    {
        try
        {
            attributes = File.GetAttributes(path);
            return true;
        }
        catch (Exception exception)
            when (exception is FileNotFoundException or DirectoryNotFoundException)
        {
            attributes = default;
            return false;
        }
    }

    private static bool IsSameFile(string left, string right)
    {
        return WindowsFileIdentity.TryRead(left, out var leftIdentity)
            && WindowsFileIdentity.TryRead(right, out var rightIdentity)
            && leftIdentity == rightIdentity;
    }
}
