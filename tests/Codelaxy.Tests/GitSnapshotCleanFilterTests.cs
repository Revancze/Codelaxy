using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// F12: the working-tree hash of an untracked file must not depend on repository-declared
// conversions. `git hash-object --stdin-paths` without `--no-filters` applies `.gitattributes`:
// it would run a repository-declared clean filter (I10) and apply `core.autocrlf`, so the
// blob identity would no longer be the identity of the bytes on disk.
//
// This test kills mutant A-MUT-3 (the untracked batch loses `--no-filters`) without a fake
// Git: it asserts on what the mutant actually does, i.e. that the filter ran and that the
// working-tree fingerprint moved with `core.autocrlf` and the filter.
//
// Safety of the fixture: everything is created under one unique temporary directory, the
// repository is initialised through GoldenGitFixture (hooks, templates, excludes, attributes,
// fsmonitor and merge options neutralised), the filter is a fixed string that only appends to
// a marker file in that directory, and it is configured with `--local`. Nothing is read from or
// written to global Git configuration, and no repository-supplied program is executed.
public sealed class GitSnapshotCleanFilterTests
{
    private const string FilterName = "codelaxy-f12";
    private const string MarkerName = "filter-ran.txt";

    // The filter runs in the work tree root; the marker lives next to the repository, inside
    // the test-owned temporary directory.
    private const string FilterCommand = "sh -c 'echo ran >> ../" + MarkerName + "; cat'";

    private const string AttributesText = "* filter=" + FilterName + "\n";
    private const string ContentFile = "crlf.txt";

    private static readonly byte[] RawContent = Encoding.ASCII.GetBytes("line-one\r\nline-two\r\n");

    // Blob IDs calculated independently of Codelaxy and Git (hashlib):
    // sha1("blob 20\0" + RawContent) and sha1("blob 18\0" + the LF-normalised content).
    private const string RawBlobOid = "126799cc6c1edb99428c1dd3e1af5eb0d1f9c301";
    private const string ConvertedBlobOid = "0eabd516bd420a48b83f5f3a814117d1ef953554";

    [Fact]
    public async Task BuildAsync_DoesNotRunCleanFilterOrConvertUntrackedFileWithAutoCrlf()
    {
        var runner = new GitProcessRunner();
        var root = Path.Combine(Path.GetTempPath(), $"Codelaxy F12 {Guid.NewGuid():N}");
        var repository = Path.Combine(root, "repository");
        var control = Path.Combine(root, "control");
        var marker = Path.Combine(root, MarkerName);

        Directory.CreateDirectory(repository);
        Directory.CreateDirectory(control);

        try
        {
            await CreateFixtureAsync(runner, repository);
            await CreateFixtureAsync(runner, control);

            // Only the repository declares the filter and enables core.autocrlf. The control
            // holds the same files but no filter driver and core.autocrlf=false.
            await GitAsync(runner, repository, "config", "--local", "core.autocrlf", "true");
            await GitAsync(
                runner,
                repository,
                "config",
                "--local",
                $"filter.{FilterName}.clean",
                FilterCommand
            );

            Assert.True(
                GitObjectHasher.TryEncodePaths(
                    [ContentFile],
                    out var pathInput,
                    out var diagnostic
                ),
                diagnostic
            );

            // Positive control: where filters are allowed, the filter really runs and the
            // blob is converted. Without this the test could pass because the fixture is inert.
            var filtered = await HashAsync(runner, repository, ["--stdin-paths"], pathInput);

            Assert.True(File.Exists(marker), "POSITIVE CONTROL: the clean filter did not run.");
            Assert.Equal(ConvertedBlobOid, filtered);

            File.Delete(marker);

            // The production invocation does not run the filter and hashes the bytes on disk.
            var unfiltered = await HashAsync(
                runner,
                repository,
                ["--no-filters", "--stdin-paths"],
                pathInput
            );

            Assert.False(File.Exists(marker), "CONTROL: --no-filters ran the clean filter.");
            Assert.Equal(RawBlobOid, unfiltered);

            var result = await new GitSnapshotBuilder(runner).BuildAsync(repository);

            Assert.True(result.Succeeded, result.Diagnostic);

            Assert.False(
                File.Exists(marker),
                "F12: BuildAsync ran the repository-declared clean filter for an untracked file."
            );

            var controlResult = await new GitSnapshotBuilder(runner).BuildAsync(control);

            Assert.True(controlResult.Succeeded, controlResult.Diagnostic);

            Assert.Equal(
                controlResult.Snapshot!.WorkingTreeFingerprint,
                result.Snapshot!.WorkingTreeFingerprint
            );
        }
        finally
        {
            DeleteDirectory(root);
        }
    }

    private static async Task CreateFixtureAsync(GitProcessRunner runner, string path)
    {
        await GoldenGitFixture.InitializeSha1Async(runner, path);

        await GitAsync(
            runner,
            path,
            "-c",
            "user.name=Codelaxy Tests",
            "-c",
            "user.email=codelaxy@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "baseline"
        );

        // Raw bytes: no newline translation may happen while the fixture is written.
        await File.WriteAllBytesAsync(
            Path.Combine(path, ".gitattributes"),
            Encoding.ASCII.GetBytes(AttributesText)
        );
        await File.WriteAllBytesAsync(Path.Combine(path, ContentFile), RawContent);
    }

    private static async Task<string> HashAsync(
        GitProcessRunner runner,
        string path,
        string[] options,
        byte[] input
    )
    {
        var result = await runner.RunReadOnlyAsync(
            path,
            ["hash-object", .. options],
            TimeSpan.FromSeconds(30),
            input
        );

        Assert.True(
            result.Succeeded,
            $"git hash-object {string.Join(' ', options)}: {result.StandardError}"
        );

        return result.StandardOutput.Trim();
    }

    private static async Task GitAsync(
        GitProcessRunner runner,
        string path,
        params string[] arguments
    )
    {
        var result = await runner.RunAsync(path, arguments, TimeSpan.FromSeconds(30));

        Assert.True(result.Succeeded, $"git {string.Join(' ', arguments)}: {result.StandardError}");
    }

    private static void DeleteDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
        {
            File.SetAttributes(file, FileAttributes.Normal);
        }

        Directory.Delete(path, recursive: true);
    }
}
