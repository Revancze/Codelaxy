namespace Codelaxy.Git;

internal sealed record WorkingTreeEntryObservationResult(
    WorkingTreeEntryObservation? Observation,
    string Diagnostic
)
{
    public bool Succeeded => Observation is not null;

    public static WorkingTreeEntryObservationResult Success(WorkingTreeEntryObservation observation)
    {
        ArgumentNullException.ThrowIfNull(observation);

        return new WorkingTreeEntryObservationResult(observation, string.Empty);
    }

    public static WorkingTreeEntryObservationResult Failure(string diagnostic)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(diagnostic);

        return new WorkingTreeEntryObservationResult(null, diagnostic);
    }
}
