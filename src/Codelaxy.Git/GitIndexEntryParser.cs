namespace Codelaxy.Git;

public static class GitIndexEntryParser
{
    public static IReadOnlyList<GitIndexEntry> Parse(string input)
    {
        ArgumentNullException.ThrowIfNull(input);

        var entries = new List<GitIndexEntry>();

        var records = input.Split('\0', StringSplitOptions.RemoveEmptyEntries);

        foreach (var record in records)
        {
            var tabIndex = record.IndexOf('\t');

            if (tabIndex < 0)
            {
                throw new FormatException("Git index record does not contain a path separator.");
            }

            var metadata = record[..tabIndex];
            var path = record[(tabIndex + 1)..];

            var fields = metadata.Split(' ', StringSplitOptions.RemoveEmptyEntries);

            var fieldOffset = fields.Length switch
            {
                3 => 0,
                4 when fields[0].Length == 1 => 1,
                _ => throw new FormatException(
                    "Git index record metadata has an unexpected format."
                ),
            };

            if (!int.TryParse(fields[fieldOffset + 2], out var stage))
            {
                throw new FormatException("Git index record contains an invalid stage.");
            }

            var skipWorktree =
                fieldOffset == 1 && string.Equals(fields[0], "S", StringComparison.Ordinal);

            entries.Add(
                new GitIndexEntry(
                    fields[fieldOffset],
                    fields[fieldOffset + 1],
                    stage,
                    path,
                    skipWorktree
                )
            );
        }

        return entries;
    }
}
