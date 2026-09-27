using System.Text.RegularExpressions;

namespace Codelaxy.Tests.Invariants;

public class ProcessBoundaryInvariantTests
{
    [Fact]
    public void ProductionCode_DoesNotUseShellIntermediary()
    {
        var repositoryRoot = FindRepositoryRoot();
        var sourceRoot = Path.Combine(repositoryRoot, "src");

        var forbiddenShellLiterals = new[]
        {
            "\"sh\"",
            "\"bash\"",
            "\"cmd\"",
            "\"cmd.exe\"",
            "\"powershell\"",
            "\"powershell.exe\"",
            "\"pwsh\"",
            "\"pwsh.exe\"",
        };

        foreach (var file in EnumerateSourceFiles(sourceRoot))
        {
            var source = File.ReadAllText(file);

            foreach (var token in forbiddenShellLiterals)
            {
                Assert.DoesNotContain(
                    token,
                    source,
                    StringComparison.OrdinalIgnoreCase);
            }
        }
    }

    [Fact]
    public void ProductionCode_DoesNotEnableShellExecution()
    {
        var repositoryRoot = FindRepositoryRoot();
        var sourceRoot = Path.Combine(repositoryRoot, "src");

        var pattern = new Regex(
            @"\bUseShellExecute\s*=\s*true\b",
            RegexOptions.IgnoreCase |
            RegexOptions.CultureInvariant);

        foreach (var file in EnumerateSourceFiles(sourceRoot))
        {
            var source = File.ReadAllText(file);

            Assert.False(
                pattern.IsMatch(source),
                $"I6 violation in {file}: " +
                "UseShellExecute must never be true.");
        }
    }

    [Fact]
    public void ProductionCode_DoesNotUseStringArguments()
    {
        var repositoryRoot = FindRepositoryRoot();
        var sourceRoot = Path.Combine(repositoryRoot, "src");

        var pattern = new Regex(
            @"\bArguments\s*=",
            RegexOptions.CultureInvariant);

        foreach (var file in EnumerateSourceFiles(sourceRoot))
        {
            var source = File.ReadAllText(file);

            Assert.False(
                pattern.IsMatch(source),
                $"I6 violation in {file}: " +
                "Process arguments must use ArgumentList.");
        }
    }

    private static IEnumerable<string> EnumerateSourceFiles(
        string directory)
    {
        return Directory
            .EnumerateFiles(
                directory,
                "*.cs",
                SearchOption.AllDirectories)
            .Where(
                path =>
                    !ContainsDirectory(path, "bin") &&
                    !ContainsDirectory(path, "obj"));
    }

    private static bool ContainsDirectory(
        string path,
        string directoryName)
    {
        var separator = Path.DirectorySeparatorChar;

        return path.Contains(
            $"{separator}{directoryName}{separator}",
            StringComparison.OrdinalIgnoreCase);
    }

    private static string FindRepositoryRoot()
    {
        DirectoryInfo? directory =
            new(AppContext.BaseDirectory);

        while (directory is not null)
        {
            if (File.Exists(
                    Path.Combine(
                        directory.FullName,
                        "Codelaxy.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new InvalidOperationException(
            "Could not locate the Codelaxy repository root.");
    }

    [Fact]
public void ProductionCode_DoesNotUseProcessStartInfoStringArgumentsConstructor()
{
    var repositoryRoot = FindRepositoryRoot();
    var sourceRoot = Path.Combine(repositoryRoot, "src");

    var pattern = new Regex(
        @"new\s+ProcessStartInfo\s*\(\s*[^,)]*,",
        RegexOptions.IgnoreCase |
        RegexOptions.CultureInvariant |
        RegexOptions.Singleline);

    foreach (var file in EnumerateSourceFiles(sourceRoot))
    {
        var source = File.ReadAllText(file);

        Assert.False(
            pattern.IsMatch(source),
            $"I6 violation in {file}: " +
            "ProcessStartInfo must not receive a string argument list. " +
            "Use ArgumentList.");
    }
}
}