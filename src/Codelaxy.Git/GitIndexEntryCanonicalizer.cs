using System.Globalization;

namespace Codelaxy.Git;

public static class GitIndexEntryCanonicalizer
{
    public static IReadOnlyList<string> Canonicalize(
        IEnumerable<GitIndexEntry> entries)
    {
        ArgumentNullException.ThrowIfNull(entries);

        var orderedEntries =
            entries
                .OrderBy(
                    entry => entry.Path,
                    StringComparer.Ordinal)
                .ThenBy(
                    entry => entry.Stage)
                .ThenBy(
                    entry => entry.Mode,
                    StringComparer.Ordinal)
                .ThenBy(
                    entry => entry.ObjectId,
                    StringComparer.Ordinal);

        var parts =
            new List<string>();

        foreach (var entry in orderedEntries)
        {
            parts.Add(entry.Mode);
            parts.Add(entry.ObjectId);
            parts.Add(
                entry.Stage.ToString(
                    CultureInfo.InvariantCulture));
            parts.Add(entry.Path);
        }

        return parts;
    }
}
