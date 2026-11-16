using System.Diagnostics;
using System.Text;

namespace Codelaxy.F10GitProxy;

// F10 test-only Git proxy. Lives in its own executable so the shared
// Codelaxy.ProcessTestHelper is never switched into proxy mode (review point 4d).
// It is active only beside a temporary copy that carries f10-git-proxy.conf:
//   line 1: fully qualified path of the real Git executable
//   line 2: victim inside "../repository": "name" or "directory/name"; with a
//           directory part the whole directory is deleted
internal static class GitProxy
{
    private const string ConfigurationFileName = "f10-git-proxy.conf";

    public static async Task<int> RunAsync(string[] arguments)
    {
        var configurationPath = Path.Combine(AppContext.BaseDirectory, ConfigurationFileName);

        if (!File.Exists(configurationPath))
        {
            await Console.Error.WriteLineAsync("F10 Git proxy configuration missing.");
            return 2;
        }

        var configuration = await File.ReadAllLinesAsync(configurationPath);

        if (
            configuration.Length != 2
            || !Path.IsPathFullyQualified(configuration[0])
            || !File.Exists(configuration[0])
            || !IsAllowedVictim(configuration[1])
        )
        {
            await Console.Error.WriteLineAsync("Invalid F10 Git proxy configuration.");
            return 2;
        }

        var realGit = configuration[0];
        var victimName = configuration[1];

        var startInfo = new ProcessStartInfo(realGit)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };

        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var git =
            Process.Start(startInfo)
            ?? throw new InvalidOperationException("Unable to launch real Git.");

        await using var output = new MemoryStream();

        await Task.WhenAll(
            ForwardInputAsync(git),
            git.StandardOutput.BaseStream.CopyToAsync(output),
            git.StandardError.BaseStream.CopyToAsync(Console.OpenStandardError()),
            git.WaitForExitAsync()
        );

        if (git.ExitCode == 0 && IsUntrackedEnumeration(arguments))
        {
            var expectedRepository = Path.GetFullPath(
                Path.Combine(AppContext.BaseDirectory, "..", "repository")
            );
            var requestedRepository = Path.GetFullPath(arguments[1]);

            if (
                !string.Equals(
                    requestedRepository,
                    expectedRepository,
                    OperatingSystem.IsWindows()
                        ? StringComparison.OrdinalIgnoreCase
                        : StringComparison.Ordinal
                )
            )
            {
                await Console.Error.WriteLineAsync("F10 repository mismatch.");
                return 5;
            }

            var bytes = output.ToArray();
            var expected = Encoding.UTF8.GetBytes(victimName + "\0");

            if (!bytes.AsSpan().SequenceEqual(expected))
            {
                await Console.Error.WriteLineAsync("F10 victim not enumerated.");
                return 3;
            }

            var victim = Path.Combine(expectedRepository, victimName);

            if (!File.Exists(victim))
            {
                await Console.Error.WriteLineAsync("F10 victim already missing.");
                return 4;
            }

            var victimDirectory = GetVictimDirectory(victimName);

            if (victimDirectory is null)
            {
                File.Delete(victim);
            }
            else
            {
                // The whole parent directory vanishes, so the builder meets a missing directory.
                Directory.Delete(
                    Path.Combine(expectedRepository, victimDirectory),
                    recursive: true
                );
            }

            await File.WriteAllBytesAsync(
                Path.Combine(AppContext.BaseDirectory, "f10-hit.bin"),
                bytes
            );
        }

        output.Position = 0;
        await output.CopyToAsync(Console.OpenStandardOutput());

        return git.ExitCode;
    }

    // "name" or "directory/name"; every part is a plain name (never ".", "..", empty,
    // rooted or containing a separator), so the victim always lies inside ../repository.
    private static bool IsAllowedVictim(string victim)
    {
        var parts = victim.Split('/');

        return parts.Length is 1 or 2 && parts.All(IsPlainFileName);
    }

    private static string? GetVictimDirectory(string victim)
    {
        var separator = victim.IndexOf('/', StringComparison.Ordinal);

        return separator < 0 ? null : victim[..separator];
    }

    private static bool IsPlainFileName(string name) =>
        name.Length > 0
        && name is not "." and not ".."
        && name.IndexOfAny(['/', '\\', '\0']) < 0
        && string.Equals(Path.GetFileName(name), name, StringComparison.Ordinal);

    private static bool IsUntrackedEnumeration(string[] arguments) =>
        arguments.Length == 6
        && arguments[0] == "-C"
        && arguments[2] == "ls-files"
        && arguments[3] == "--others"
        && arguments[4] == "--exclude-per-directory=.gitignore"
        && arguments[5] == "-z";

    private static async Task ForwardInputAsync(Process git)
    {
        try
        {
            await Console.OpenStandardInput().CopyToAsync(git.StandardInput.BaseStream);
        }
        catch (IOException) when (git.HasExited)
        {
            // Git can finish before consuming all standard input.
        }
        finally
        {
            git.StandardInput.Close();
        }
    }
}
