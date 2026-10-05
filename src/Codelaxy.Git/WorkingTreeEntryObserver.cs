using System.Security;

namespace Codelaxy.Git;

internal sealed class WorkingTreeEntryObserver
{
    private readonly string _repositoryTopLevel;

    private readonly Dictionary<string, IReadOnlyDictionary<string, string>> _directoryEntries =
        new(StringComparer.Ordinal);

    public WorkingTreeEntryObserver(string repositoryTopLevel)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(repositoryTopLevel);

        _repositoryTopLevel = Path.GetFullPath(repositoryTopLevel);
    }

    public WorkingTreeEntryObservationResult Observe(string relativePath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(relativePath);

        try
        {
            var observation = ObserveCore(relativePath);

            return WorkingTreeEntryObservationResult.Success(observation);
        }
        catch (Exception exception)
            when (exception is IOException or UnauthorizedAccessException or SecurityException)
        {
            return WorkingTreeEntryObservationResult.Failure(
                $"Unable to observe working-tree path " + $"'{relativePath}': {exception.Message}"
            );
        }
    }

    private WorkingTreeEntryObservation ObserveCore(string relativePath)
    {
        var segments = relativePath.Split('/', StringSplitOptions.RemoveEmptyEntries);

        var currentDirectory = _repositoryTopLevel;

        for (var index = 0; index < segments.Length; ++index)
        {
            var segment = segments[index];

            var entries = GetDirectoryEntries(currentDirectory);

            if (!entries.TryGetValue(segment, out var exactPath))
            {
                return Missing(relativePath);
            }

            var isFinalSegment = index == segments.Length - 1;

            var fileInfo = new FileInfo(exactPath);
            var linkTarget = fileInfo.LinkTarget;
            var attributes = File.GetAttributes(exactPath);

            var isReparsePoint = (attributes & FileAttributes.ReparsePoint) != 0;

            var isDirectory = (attributes & FileAttributes.Directory) != 0;

            if (!isFinalSegment)
            {
                if (linkTarget is not null || isReparsePoint || !isDirectory)
                {
                    return Missing(relativePath);
                }

                currentDirectory = exactPath;

                continue;
            }

            if (OperatingSystem.IsWindows() && isReparsePoint)
            {
                if (!isDirectory && linkTarget is not null)
                {
                    return new WorkingTreeEntryObservation(
                        relativePath,
                        WorkingTreeEntryKind.SymbolicLink,
                        "120000"
                    );
                }

                return new WorkingTreeEntryObservation(
                    relativePath,
                    WorkingTreeEntryKind.ReparsePoint,
                    null
                );
            }

            if (linkTarget is not null)
            {
                return new WorkingTreeEntryObservation(
                    relativePath,
                    WorkingTreeEntryKind.SymbolicLink,
                    "120000"
                );
            }

            if (isReparsePoint)
            {
                return new WorkingTreeEntryObservation(
                    relativePath,
                    WorkingTreeEntryKind.ReparsePoint,
                    null
                );
            }

            if (isDirectory)
            {
                return new WorkingTreeEntryObservation(
                    relativePath,
                    WorkingTreeEntryKind.Directory,
                    null
                );
            }

            return new WorkingTreeEntryObservation(
                relativePath,
                WorkingTreeEntryKind.RegularFile,
                GetRegularFileMode(exactPath)
            );
        }

        return Missing(relativePath);
    }

    private IReadOnlyDictionary<string, string> GetDirectoryEntries(string directoryPath)
    {
        if (_directoryEntries.TryGetValue(directoryPath, out var cachedEntries))
        {
            return cachedEntries;
        }

        var entries = new Dictionary<string, string>(StringComparer.Ordinal);

        foreach (var entry in Directory.EnumerateFileSystemEntries(directoryPath))
        {
            var name = Path.GetFileName(entry);

            entries[name] = entry;
        }

        _directoryEntries.Add(directoryPath, entries);

        return entries;
    }

    private static WorkingTreeEntryObservation Missing(string relativePath)
    {
        return new WorkingTreeEntryObservation(relativePath, WorkingTreeEntryKind.Missing, null);
    }

    private static string? GetRegularFileMode(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            return null;
        }

        var mode = File.GetUnixFileMode(path);

        return (mode & UnixFileMode.UserExecute) != 0 ? "100755" : "100644";
    }
}
