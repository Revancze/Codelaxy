using System.Text;

namespace Codelaxy.Git;

// Observes Git metadata without deciding whether an executable is trusted.
internal static class GitMetadataObservation
{
    private const long MaxMetadataFileLength = 1 << 20;

    private static readonly Encoding MetadataEncoding = new UTF8Encoding(
        encoderShouldEmitUTF8Identifier: false
    );

    internal enum ReadStatus
    {
        Valid,
        Missing,
        Invalid,
        Indeterminate,
    }

    internal static (ReadStatus Status, string? Value) Read(string path, string prefix)
    {
        try
        {
            return ReadExisting(path, prefix);
        }
        catch (FileNotFoundException)
        {
            return (ReadStatus.Missing, null);
        }
        catch (DirectoryNotFoundException)
        {
            return (ReadStatus.Missing, null);
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
            return (ReadStatus.Indeterminate, null);
        }
    }

    private static (ReadStatus Status, string? Value) ReadExisting(string path, string prefix)
    {
        var attributes = File.GetAttributes(path);

        if ((attributes & FileAttributes.Directory) != FileAttributes.None)
        {
            return (ReadStatus.Invalid, null);
        }

        var length = new FileInfo(path).Length;

        if (length == 0 || length > MaxMetadataFileLength)
        {
            return (ReadStatus.Invalid, null);
        }

        var content = MetadataEncoding.GetString(File.ReadAllBytes(path));

        if (!content.StartsWith(prefix, StringComparison.Ordinal))
        {
            return (ReadStatus.Invalid, null);
        }

        var value = content[prefix.Length..].TrimEnd('\r', '\n');

        return value.Length == 0 ? (ReadStatus.Invalid, null) : (ReadStatus.Valid, value);
    }
}
