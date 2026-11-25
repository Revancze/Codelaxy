namespace Codelaxy.Tests;

// A theory that needs Linux file permissions to be enforced. A privileged process
// (root) bypasses them, so the theory is reported as skipped on other systems and
// for a privileged process instead of passing without checking anything.
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
