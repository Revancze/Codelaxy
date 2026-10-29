namespace Codelaxy.Git;

internal static class GitStagedBaseModes
{
    internal static IReadOnlyDictionary<string, string> ParseStagedBaseModes(string rawDiff)
    {
        var modes = new Dictionary<string, string>(StringComparer.Ordinal);

        var records = rawDiff.Split('\0', StringSplitOptions.RemoveEmptyEntries);

        if (records.Length % 2 != 0)
        {
            throw new FormatException("Git raw diff output contains an incomplete record.");
        }

        for (var index = 0; index < records.Length; index += 2)
        {
            var metadata = records[index];
            var path = records[index + 1];

            if (!metadata.StartsWith(':'))
            {
                throw new FormatException("Git raw diff record has an unexpected format.");
            }

            var fields = metadata[1..].Split(' ', StringSplitOptions.RemoveEmptyEntries);

            if (fields.Length != 5)
            {
                throw new FormatException("Git raw diff metadata has an unexpected format.");
            }

            var oldMode = fields[0];
            var newMode = fields[1];

            if (oldMode != newMode && IsRegularFileMode(oldMode) && IsRegularFileMode(newMode))
            {
                modes[path] = oldMode;
            }
        }

        return modes;
    }

    private static bool IsRegularFileMode(string mode)
    {
        return mode is "100644" or "100755";
    }

    internal static string? GetWindowsWorkingTreeRegularFileMode(
        string path,
        IReadOnlyList<GitIndexEntry> indexEntries,
        IReadOnlyDictionary<string, string> stagedBaseModes
    )
    {
        if (
            stagedBaseModes.TryGetValue(path, out var stagedBaseMode)
            && IsRegularFileMode(stagedBaseMode)
        )
        {
            return stagedBaseMode;
        }

        var regularModes = indexEntries
            .Select(entry => entry.Mode)
            .Where(IsRegularFileMode)
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        return regularModes.Length == 1 ? regularModes[0] : null;
    }
}
