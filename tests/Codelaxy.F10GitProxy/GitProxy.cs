using System.Diagnostics;
using System.Text;

namespace Codelaxy.F10GitProxy;

// F10 test-only Git proxy. Lives in its own executable so the shared
// Codelaxy.ProcessTestHelper is never switched into proxy mode (review point 4d).
// It is active only beside a temporary copy that carries f10-git-proxy.conf:
//   line 1: fully qualified path of the real Git executable
//   line 2: victim inside "../repository": "name" or "directory/name"; with a
//           directory part the whole directory is deleted
//   line 3 (optional, CR-003): trigger mode; a missing line means "untracked"
//     untracked: after `ls-files --others --exclude-per-directory=.gitignore -z`
//                whose whole output is exactly the victim (F10, unchanged)
//     index:     after the first `ls-files --stage -t -z` that lists the victim
//     hash:      before the first `hash-object --no-filters --stdin-paths`
//   "index" and "hash" fire once: when f10-hit.bin exists the proxy only forwards,
//   so the builder's later reads of the index see the real state, not a proxy error.
internal static class GitProxy
{
    private const string ConfigurationFileName = "f10-git-proxy.conf";
    private const string HitFileName = "f10-hit.bin";

    private const string UntrackedMode = "untracked";
    private const string IndexMode = "index";
    private const string HashMode = "hash";

    public static async Task<int> RunAsync(string[] arguments)
    {
        var configuration = await ReadConfigurationAsync();

        if (configuration is null)
        {
            return 2;
        }

        var expectedRepository = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "repository")
        );
        var hitPath = Path.Combine(AppContext.BaseDirectory, HitFileName);
        var armed = configuration.Mode != UntrackedMode && !File.Exists(hitPath);

        byte[]? standardInput = null;

        if (armed && configuration.Mode == HashMode && IsStdinPathsHashRequest(arguments))
        {
            if (!IsExpectedRepository(arguments[1], expectedRepository))
            {
                await Console.Error.WriteLineAsync("F10 repository mismatch.");
                return 5;
            }

            // Read the paths first so the hit file records what the builder asked for.
            standardInput = await ReadStandardInputAsync();

            var deleted = await DeleteVictimAsync(expectedRepository, configuration.Victim);

            if (deleted != 0)
            {
                return deleted;
            }

            await File.WriteAllBytesAsync(hitPath, standardInput);
        }

        var (exitCode, output) = await RunRealGitAsync(
            configuration.RealGit,
            arguments,
            standardInput
        );

        if (exitCode == 0)
        {
            var triggered = await TriggerAfterListingAsync(
                configuration,
                armed,
                arguments,
                output,
                expectedRepository,
                hitPath
            );

            if (triggered != 0)
            {
                return triggered;
            }
        }

        await Console.OpenStandardOutput().WriteAsync(output);

        return exitCode;
    }

    private static async Task<ProxyConfiguration?> ReadConfigurationAsync()
    {
        var configurationPath = Path.Combine(AppContext.BaseDirectory, ConfigurationFileName);

        if (!File.Exists(configurationPath))
        {
            await Console.Error.WriteLineAsync("F10 Git proxy configuration missing.");
            return null;
        }

        var lines = await File.ReadAllLinesAsync(configurationPath);

        if (
            lines.Length is not (2 or 3)
            || !Path.IsPathFullyQualified(lines[0])
            || !File.Exists(lines[0])
            || !IsAllowedVictim(lines[1])
            || (lines.Length == 3 && !IsKnownMode(lines[2]))
        )
        {
            await Console.Error.WriteLineAsync("Invalid F10 Git proxy configuration.");
            return null;
        }

        return new ProxyConfiguration(
            lines[0],
            lines[1],
            lines.Length == 3 ? lines[2] : UntrackedMode
        );
    }

    // Deletes the victim after a listing that names it: the untracked enumeration
    // (F10) or, once, the index listing (CR-003). Returns 0 when nothing applies.
    private static async Task<int> TriggerAfterListingAsync(
        ProxyConfiguration configuration,
        bool armed,
        string[] arguments,
        byte[] output,
        string expectedRepository,
        string hitPath
    )
    {
        bool victimListed;

        if (configuration.Mode == UntrackedMode && IsUntrackedEnumeration(arguments))
        {
            var expected = Encoding.UTF8.GetBytes(configuration.Victim + "\0");
            victimListed = output.AsSpan().SequenceEqual(expected);
        }
        else if (armed && configuration.Mode == IndexMode && IsIndexEnumeration(arguments))
        {
            victimListed = IndexListsPath(output, configuration.Victim);
        }
        else
        {
            return 0;
        }

        if (!IsExpectedRepository(arguments[1], expectedRepository))
        {
            await Console.Error.WriteLineAsync("F10 repository mismatch.");
            return 5;
        }

        if (!victimListed)
        {
            await Console.Error.WriteLineAsync("F10 victim not enumerated.");
            return 3;
        }

        var deleted = await DeleteVictimAsync(expectedRepository, configuration.Victim);

        if (deleted != 0)
        {
            return deleted;
        }

        await File.WriteAllBytesAsync(hitPath, output);

        return 0;
    }

    private static async Task<(int ExitCode, byte[] Output)> RunRealGitAsync(
        string realGit,
        string[] arguments,
        byte[]? standardInput
    )
    {
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
            ForwardInputAsync(git, standardInput),
            git.StandardOutput.BaseStream.CopyToAsync(output),
            git.StandardError.BaseStream.CopyToAsync(Console.OpenStandardError()),
            git.WaitForExitAsync()
        );

        return (git.ExitCode, output.ToArray());
    }

    private static async Task<byte[]> ReadStandardInputAsync()
    {
        await using var input = new MemoryStream();
        await Console.OpenStandardInput().CopyToAsync(input);

        return input.ToArray();
    }

    private static async Task<int> DeleteVictimAsync(string repository, string victimName)
    {
        var victim = Path.Combine(repository, victimName);

        // A symbolic link counts as present even when File.Exists cannot follow it.
        if (!File.Exists(victim) && new FileInfo(victim).LinkTarget is null)
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
            Directory.Delete(Path.Combine(repository, victimDirectory), recursive: true);
        }

        return 0;
    }

    private static bool IsExpectedRepository(string requested, string expectedRepository) =>
        string.Equals(
            Path.GetFullPath(requested),
            expectedRepository,
            OperatingSystem.IsWindows()
                ? StringComparison.OrdinalIgnoreCase
                : StringComparison.Ordinal
        );

    private static bool IsKnownMode(string mode) => mode is UntrackedMode or IndexMode or HashMode;

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

    // `ls-files --stage -t -z` entries look like "H 100644 <oid> 0\t<path>\0".
    private static bool IndexListsPath(byte[] output, string path) =>
        Encoding
            .UTF8.GetString(output)
            .Split('\0', StringSplitOptions.RemoveEmptyEntries)
            .Any(entry =>
            {
                var tab = entry.IndexOf('\t', StringComparison.Ordinal);

                return tab >= 0
                    && string.Equals(entry[(tab + 1)..], path, StringComparison.Ordinal);
            });

    private static bool IsUntrackedEnumeration(string[] arguments) =>
        arguments.Length == 6
        && arguments[0] == "-C"
        && arguments[2] == "ls-files"
        && arguments[3] == "--others"
        && arguments[4] == "--exclude-per-directory=.gitignore"
        && arguments[5] == "-z";

    private static bool IsIndexEnumeration(string[] arguments) =>
        arguments.Length == 6
        && arguments[0] == "-C"
        && arguments[2] == "ls-files"
        && arguments[3] == "--stage"
        && arguments[4] == "-t"
        && arguments[5] == "-z";

    private static bool IsStdinPathsHashRequest(string[] arguments) =>
        arguments.Length == 5
        && arguments[0] == "-C"
        && arguments[2] == "hash-object"
        && arguments[3] == "--no-filters"
        && arguments[4] == "--stdin-paths";

    private static async Task ForwardInputAsync(Process git, byte[]? alreadyRead)
    {
        try
        {
            if (alreadyRead is null)
            {
                await Console.OpenStandardInput().CopyToAsync(git.StandardInput.BaseStream);
            }
            else
            {
                await git.StandardInput.BaseStream.WriteAsync(alreadyRead);
            }
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

    private sealed record ProxyConfiguration(string RealGit, string Victim, string Mode);
}
