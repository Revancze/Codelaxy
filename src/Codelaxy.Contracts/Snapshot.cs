namespace Codelaxy.Contracts;

public sealed record Snapshot
{
    public required int SchemaVersion
    {
        get;
        init
        {
            ArgumentOutOfRangeException.ThrowIfLessThan(value, 1);

            field = value;
        }
    }

    public required string HeadFingerprint
    {
        get;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            field = value;
        }
    }

    public required string IndexFingerprint
    {
        get;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            field = value;
        }
    }

    public required string WorkingTreeFingerprint
    {
        get;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            field = value;
        }
    }

    public required string StagedFingerprint
    {
        get;
        init
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(value);

            field = value;
        }
    }
}
