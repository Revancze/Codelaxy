namespace Codelaxy.Git;

public sealed record GitCommandResult(
    int? ExitCode,
    string StandardOutput,
    string StandardError,
    GitCommandFailureKind FailureKind = GitCommandFailureKind.None
)
{
    public bool Started => ExitCode.HasValue;

    public bool Succeeded => Started && FailureKind == GitCommandFailureKind.None && ExitCode == 0;
}
