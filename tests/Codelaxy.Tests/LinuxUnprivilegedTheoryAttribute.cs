namespace Codelaxy.Tests;

// The theory form of LinuxUnprivilegedFact: Linux file permissions must be enforced,
// so the theory is reported as skipped on other systems and for a privileged process.
[AttributeUsage(AttributeTargets.Method)]
public sealed class LinuxUnprivilegedTheoryAttribute : TheoryAttribute
{
    public LinuxUnprivilegedTheoryAttribute()
    {
        if (!OperatingSystem.IsLinux())
        {
            Skip = "Requires Linux file permissions.";
        }
        else if (Environment.IsPrivilegedProcess)
        {
            Skip = "Requires an unprivileged user: a privileged process bypasses file permissions.";
        }
    }
}
