using System.Buffers;
using System.Text.Json;

namespace Codelaxy.Contracts;

public static class SnapshotSerializer
{
    private const string RecordType = "snapshot";
    private const int SupportedSchemaVersion = 1;

    public static byte[] Serialize(Snapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);

        if (snapshot.SchemaVersion != SupportedSchemaVersion)
        {
            throw new ArgumentException(
                $"Unsupported snapshot schema version: {snapshot.SchemaVersion}.",
                nameof(snapshot)
            );
        }

        var buffer = new ArrayBufferWriter<byte>();

        using (var writer = new Utf8JsonWriter(buffer))
        {
            writer.WriteStartObject();

            writer.WriteString("recordType", RecordType);

            writer.WriteNumber("schemaVersion", snapshot.SchemaVersion);

            writer.WriteString("headFingerprint", snapshot.HeadFingerprint);

            writer.WriteString("indexFingerprint", snapshot.IndexFingerprint);

            writer.WriteString("workingTreeFingerprint", snapshot.WorkingTreeFingerprint);

            writer.WriteString("stagedFingerprint", snapshot.StagedFingerprint);

            writer.WriteEndObject();
        }

        return buffer.WrittenSpan.ToArray();
    }

    public static Snapshot Deserialize(byte[] input)
    {
        ArgumentNullException.ThrowIfNull(input);

        using var document = JsonDocument.Parse(input);

        var root = document.RootElement;

        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new FormatException("Snapshot record must be a JSON object.");
        }

        var recordType = GetRequiredString(root, "recordType");

        if (!string.Equals(recordType, RecordType, StringComparison.Ordinal))
        {
            throw new FormatException($"Unknown record type: {recordType}.");
        }

        if (
            !root.TryGetProperty("schemaVersion", out var schemaVersionElement)
            || !schemaVersionElement.TryGetInt32(out var schemaVersion)
        )
        {
            throw new FormatException("Snapshot record has an invalid schemaVersion.");
        }

        if (schemaVersion != SupportedSchemaVersion)
        {
            throw new FormatException(
                $"Unsupported snapshot schema version: " + $"{schemaVersion}."
            );
        }

        return new Snapshot
        {
            SchemaVersion = schemaVersion,
            HeadFingerprint = GetRequiredString(root, "headFingerprint"),
            IndexFingerprint = GetRequiredString(root, "indexFingerprint"),
            WorkingTreeFingerprint = GetRequiredString(root, "workingTreeFingerprint"),
            StagedFingerprint = GetRequiredString(root, "stagedFingerprint"),
        };
    }

    private static string GetRequiredString(JsonElement root, string propertyName)
    {
        if (
            !root.TryGetProperty(propertyName, out var element)
            || element.ValueKind != JsonValueKind.String
        )
        {
            throw new FormatException(
                $"Snapshot record is missing " + $"required string property '{propertyName}'."
            );
        }

        return element.GetString()!;
    }
}
