namespace Codelaxy.Git;

public static class GitIndexEntryParser
{
    public static IReadOnlyList<GitIndexEntry> Parse(
        string input)
    {
        ArgumentNullException.ThrowIfNull(input);

        var entries =
            new List<GitIndexEntry>();

        var records =
            input.Split(
                '\0',
                StringSplitOptions.RemoveEmptyEntries);

        foreach (var record in records)
        {
            var tabIndex =
                record.IndexOf('\t');

            if (tabIndex < 0)
            {
                throw new FormatException(
                    "Git index record does not contain a path separator.");
            }

            var metadata =
                record[..tabIndex];

            var path =
                record[(tabIndex + 1)..];

            var fields =
                metadata.Split(
                    ' ',
                    StringSplitOptions.RemoveEmptyEntries);

            if (fields.Length != 3)
            {
                throw new FormatException(
                    "Git index record metadata has an unexpected format.");
            }

            if (!int.TryParse(
                    fields[2],
                    out var stage))
            {
                throw new FormatException(
                    "Git index record contains an invalid stage.");
            }

            entries.Add(
                new GitIndexEntry(
                    fields[0],
                    fields[1],
                    stage,
                    path));
        }

        return entries;
    }
}