using System.Reflection;
using Xunit.Sdk;

namespace Codelaxy.Tests;

// Inline data for a theory case that only means something on Linux, such as a
// symbolic link. On other systems the case is reported as skipped instead of
// passing without checking anything.
[AttributeUsage(AttributeTargets.Method, AllowMultiple = true)]
public sealed class LinuxOnlyInlineDataAttribute : DataAttribute
{
    private readonly object[] _data;

    public LinuxOnlyInlineDataAttribute(params object[] values)
    {
        _data = values;

        if (!OperatingSystem.IsLinux())
        {
            Skip = "Requires Linux symbolic links.";
        }
    }

    public IReadOnlyList<object> Values => _data;

    public override IEnumerable<object[]> GetData(MethodInfo testMethod) => [_data];
}
