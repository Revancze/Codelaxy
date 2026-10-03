namespace Codelaxy.Tests.Invariants;

public class TimestampIdentityInvariantTests
{
    [Fact]
    public void CoreAndContracts_DoNotUseTimestampsAsIdentityInputs()
    {
        var repositoryRoot = FindRepositoryRoot();

        var sourceDirectories = new[]
        {
            Path.Combine(repositoryRoot, "src", "Codelaxy.Core"),
            Path.Combine(repositoryRoot, "src", "Codelaxy.Contracts"),
        };

        var forbiddenTokens = new[]
        {
            "DateTime",
            "DateTimeOffset",
            "LastWriteTime",
            "CreationTime",
            "LastAccessTime",
            "GetLastWriteTime",
            "GetCreationTime",
            "GetLastAccessTime",
        };

        foreach (var sourceDirectory in sourceDirectories)
        {
            foreach (var file in EnumerateSourceFiles(sourceDirectory))
            {
                var source = File.ReadAllText(file);

                foreach (var token in forbiddenTokens)
                {
                    Assert.DoesNotContain(token, source, StringComparison.Ordinal);
                }
            }
        }
    }

    private static IEnumerable<string> EnumerateSourceFiles(string directory)
    {
        return Directory
            .EnumerateFiles(directory, "*.cs", SearchOption.AllDirectories)
            .Where(path => !ContainsDirectory(path, "bin") && !ContainsDirectory(path, "obj"));
    }

    private static bool ContainsDirectory(string path, string directoryName)
    {
        var separator = Path.DirectorySeparatorChar;

        return path.Contains(
            $"{separator}{directoryName}{separator}",
            StringComparison.OrdinalIgnoreCase
        );
    }

    private static string FindRepositoryRoot()
    {
        DirectoryInfo? directory = new(AppContext.BaseDirectory);

        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Codelaxy.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new InvalidOperationException("Could not locate the Codelaxy repository root.");
    }
}
