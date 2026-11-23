namespace Codelaxy.Tests;

// A fact that needs Linux file permissions to be enforced. A privileged process
// (root) bypasses directory permissions, so the test's precondition cannot hold
// there; the test is then reported as skipped instead of passing silently.
[AttributeUsage(AttributeTargets.Method)]
public sealed class LinuxUnprivilegedFactAttribute : FactAttribute
{
    public LinuxUnprivilegedFactAttribute()
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
