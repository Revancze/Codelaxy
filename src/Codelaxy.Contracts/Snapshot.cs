namespace Codelaxy.Contracts;

public sealed record Snapshot
{
    private int _schemaVersion;
    private string _headFingerprint = null!;
    private string _indexFingerprint = null!;
    private string _workingTreeFingerprint = null!;
    private string _stagedFingerprint = null!;

    public required int SchemaVersion
    {
        get => _schemaVersion;
        init
        {
            ArgumentOutOfRangeException.ThrowIfLessThan(value, 1);

            _schemaVersion = value;
        }
    }

    public required string HeadFingerprint
    {
        get => _headFingerprint;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            _headFingerprint = value;
        }
    }

    public required string IndexFingerprint
    {
        get => _indexFingerprint;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            _indexFingerprint = value;
        }
    }

    public required string WorkingTreeFingerprint
    {
        get => _workingTreeFingerprint;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            _workingTreeFingerprint = value;
        }
    }

    public required string StagedFingerprint
    {
        get => _stagedFingerprint;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            _stagedFingerprint = value;
        }
    }
}
