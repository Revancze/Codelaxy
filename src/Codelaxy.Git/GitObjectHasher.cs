using System.Text;

namespace Codelaxy.Git;

internal static class GitObjectHasher
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    internal static bool TryEncodePaths(
        IReadOnlyList<string> paths,
        out byte[] input,
        out string diagnostic
    )
    {
        var builder = new StringBuilder();

        foreach (var path in paths)
        {
            if (string.IsNullOrEmpty(path) || path.Contains('\0', StringComparison.Ordinal))
            {
                input = [];
                diagnostic = "Unsupported path for git hash-object --stdin-paths.";
                return false;
            }

            byte[] bytes;

            try
            {
                bytes = StrictUtf8.GetBytes(path);
            }
            catch (EncoderFallbackException)
            {
                input = [];
                diagnostic = "Repository path is not valid UTF-8.";
                return false;
            }

            builder.Append('"');

            foreach (var value in bytes)
            {
                if (value >= 33 && value <= 126 && value != '"' && value != '\\')
                {
                    builder.Append((char)value);
                }
                else
                {
                    builder.Append('\\');
                    builder.Append((char)('0' + (value >> 6)));
                    builder.Append((char)('0' + ((value >> 3) & 7)));
                    builder.Append((char)('0' + (value & 7)));
                }
            }

            builder.Append('"');
            builder.Append('\n');
        }

        input = StrictUtf8.GetBytes(builder.ToString());
        diagnostic = string.Empty;
        return true;
    }

    internal static bool TryParseObjectIds(string output, int expectedCount, out string[] objectIds)
    {
        objectIds = output.Split('\n');

        if (objectIds.Length > 0 && objectIds[^1].Length == 0)
        {
            objectIds = objectIds[..^1];
        }

        if (objectIds.Length != expectedCount)
        {
            return false;
        }

        var expectedLength = objectIds.Length > 0 ? objectIds[0].Length : 0;

        return !objectIds.Any(objectId =>
            (objectId.Length != 40 && objectId.Length != 64)
            || objectId.Length != expectedLength
            || objectId.Any(character => character is not (>= '0' and <= '9' or >= 'a' and <= 'f'))
        );
    }
}
