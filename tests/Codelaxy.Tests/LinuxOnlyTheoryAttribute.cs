namespace Codelaxy.Tests;

[AttributeUsage(AttributeTargets.Method)]
public sealed class LinuxOnlyTheoryAttribute : TheoryAttribute
{
    public LinuxOnlyTheoryAttribute()
    {
        if (!OperatingSystem.IsLinux())
        {
            Skip = "Requires Linux filename semantics.";
        }
    }
}
