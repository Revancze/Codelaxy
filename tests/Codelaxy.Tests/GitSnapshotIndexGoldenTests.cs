using System.Buffers.Binary;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// Golden tests for the index identity (I), canonical v2.
//
// Expected values were computed independently of Codelaxy with Python hashlib
// (golden_index_reference.py, golden_index_unicode_reference.py); every blob id
// was cross-checked with `git hash-object`. They are not outputs of this code.
//
// Canonical v2: entries ordered by path (UTF-16 code units, StringComparer.Ordinal),
// then stage, mode, object id; each entry contributes mode, object id, stage and
// path; domain and parts are framed as uint32 big-endian UTF-8 length + UTF-8 bytes
// and hashed with SHA-256. The skip-worktree flag is not part of I.
public class GitSnapshotIndexGoldenTests
{
    private const string IndexDomain = "codelaxy.snapshot.index.v2";

    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    // ---------------------------------------------------------------- INDEX-GOLDEN-001

    private const string Golden001 =
        "sha256:9f3855d36ef48a221dfe8f962467bd1e321600f3ee14af623761b26c2227f92a";

    private const string Golden001AlphaOid = "4a58007052a65fbc2fc3f910f2855f45a4058e74";
    private const string Golden001CharlieOid = "7e5ac7112f1bef9d3bbefe883a8a8441aae3c36a";
    private const string Golden001RunOid = "1a2485251c33a70432394c93fb89330ef214bfc9";
    private const string Golden001LinkOid = "8d14cbf983b3fad683171c9418998d9f68340823";
    private const string Golden001BaseOid = "df967b96a579e45a18b8251732d16804b2e56a55";
    private const string Golden001OursOid = "b19a1e93bec1317dc6097229e12afaffbfa74dc2";
    private const string Golden001TheirsOid = "950b81b7eee953d050aa05a641f8e056c85dd1bd";
    private const string Golden001ZetOid = "1f168fa297b2b8c75c9f1f87ef76bf13963f39c5";

    // Canonical order: "C.txt" (U+0043) sorts before "a.txt" (U+0061).
    private static readonly string[] Golden001Parts =
    [
        "100644",
        Golden001CharlieOid,
        "0",
        "C.txt",
        "100644",
        Golden001AlphaOid,
        "0",
        "a.txt",
        "100755",
        Golden001RunOid,
        "0",
        "dir/run.sh",
        "120000",
        Golden001LinkOid,
        "0",
        "link",
        "100644",
        Golden001BaseOid,
        "1",
        "m.txt",
        "100644",
        Golden001OursOid,
        "2",
        "m.txt",
        "100644",
        Golden001TheirsOid,
        "3",
        "m.txt",
        "100644",
        Golden001ZetOid,
        "0",
        "ž.txt",
    ];

    [Fact]
    public void IndexGolden001_CanonicalPartsMatchIndependentReference()
    {
        // Intentionally shuffled input (not Git index order), with skip-worktree on a.txt.
        var entries = new[]
        {
            new GitIndexEntry("100644", Golden001ZetOid, 0, "ž.txt"),
            new GitIndexEntry("100644", Golden001TheirsOid, 3, "m.txt"),
            new GitIndexEntry("100644", Golden001AlphaOid, 0, "a.txt", SkipWorktree: true),
            new GitIndexEntry("120000", Golden001LinkOid, 0, "link"),
            new GitIndexEntry("100644", Golden001BaseOid, 1, "m.txt"),
            new GitIndexEntry("100755", Golden001RunOid, 0, "dir/run.sh"),
            new GitIndexEntry("100644", Golden001OursOid, 2, "m.txt"),
            new GitIndexEntry("100644", Golden001CharlieOid, 0, "C.txt"),
        };

        var parts = GitIndexEntryCanonicalizer.Canonicalize(entries);

        Assert.Equal(Golden001Parts, parts);
        Assert.Equal(Golden001, ReferenceFingerprint(IndexDomain, parts));
    }

    [Fact]
    public async Task IndexGolden001_GitFixtureProducesExpectedIndexFingerprint()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await CreateGolden001FixtureAsync(runner, repositoryPath);

            var result = await new GitSnapshotBuilder(runner).BuildAsync(repositoryPath);

            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.Equal(Golden001, result.Snapshot!.IndexFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task IndexGolden001_SkipWorktreeDoesNotChangeIndexFingerprint()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await CreateGolden001FixtureAsync(runner, repositoryPath);

            var builder = new GitSnapshotBuilder(runner);

            var withFlag = await builder.BuildAsync(repositoryPath);

            await RunGitAsync(
                runner,
                repositoryPath,
                "update-index",
                "--no-skip-worktree",
                "a.txt"
            );

            Assert.StartsWith(
                "H 100644 " + Golden001AlphaOid + " 0\ta.txt\0",
                await LsFilesAsync(runner, repositoryPath, "a.txt"),
                StringComparison.Ordinal
            );

            var withoutFlag = await builder.BuildAsync(repositoryPath);

            Assert.True(withFlag.Succeeded, withFlag.Diagnostic);
            Assert.True(withoutFlag.Succeeded, withoutFlag.Diagnostic);
            Assert.Equal(Golden001, withFlag.Snapshot!.IndexFingerprint);
            Assert.Equal(Golden001, withoutFlag.Snapshot!.IndexFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    private static async Task CreateGolden001FixtureAsync(
        GitProcessRunner runner,
        string repositoryPath
    )
    {
        await InitializeSha1RepositoryAsync(runner, repositoryPath);

        // Stages 1/2/3 for m.txt from an ordinary three-way merge conflict.
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "m.txt"), "base\n");
        await RunGitAsync(runner, repositoryPath, "add", "m.txt");
        await CommitAsync(runner, repositoryPath, "base");

        await RunGitAsync(runner, repositoryPath, "checkout", "-q", "-b", "theirs");
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "m.txt"), "theirs\n");
        await RunGitAsync(runner, repositoryPath, "add", "m.txt");
        await CommitAsync(runner, repositoryPath, "theirs");

        await RunGitAsync(runner, repositoryPath, "checkout", "-q", "main");
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "m.txt"), "ours\n");
        await RunGitAsync(runner, repositoryPath, "add", "m.txt");
        await CommitAsync(runner, repositoryPath, "ours");

        var merge = await runner.RunAsync(
            repositoryPath,
            [
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "merge",
                "--no-edit",
                "theirs",
            ]
        );

        // The merge must stop on exactly this conflict, not fail for another reason.
        Assert.Equal(1, merge.ExitCode);
        Assert.True(File.Exists(Path.Combine(repositoryPath, ".git", "MERGE_HEAD")));
        Assert.Equal(
            $"100644 {Golden001BaseOid} 1\tm.txt\0"
                + $"100644 {Golden001OursOid} 2\tm.txt\0"
                + $"100644 {Golden001TheirsOid} 3\tm.txt\0",
            await RunGitReadAsync(runner, repositoryPath, "ls-files", "--unmerged", "-z")
        );

        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "a.txt"), "alpha\n");
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "C.txt"), "charlie\n");
        Directory.CreateDirectory(Path.Combine(repositoryPath, "dir"));
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "dir", "run.sh"), "#!/bin/sh\n");
        await File.WriteAllTextAsync(Path.Combine(repositoryPath, "ž.txt"), "zet\n");

        await RunGitAsync(
            runner,
            repositoryPath,
            "add",
            "--",
            "a.txt",
            "C.txt",
            "dir/run.sh",
            "ž.txt"
        );
        await RunGitAsync(runner, repositoryPath, "update-index", "--chmod=+x", "dir/run.sh");

        // Mode and symlink-ness live in the index only: no dependence on core.symlinks
        // or the executable bit of the host filesystem.
        var linkPayload = Path.Combine(repositoryPath, "link.payload");
        await File.WriteAllTextAsync(linkPayload, "a.txt");
        var linkOid = (
            await RunGitReadAsync(
                runner,
                repositoryPath,
                "hash-object",
                "-w",
                "--no-filters",
                "--",
                "link.payload"
            )
        ).Trim();
        File.Delete(linkPayload);
        Assert.Equal(Golden001LinkOid, linkOid);
        await RunGitAsync(
            runner,
            repositoryPath,
            "update-index",
            "--add",
            "--cacheinfo",
            $"120000,{Golden001LinkOid},link"
        );

        await RunGitAsync(runner, repositoryPath, "update-index", "--skip-worktree", "a.txt");

        // Exactly these eight entries, in Git's own (UTF-8) order, with tags.
        Assert.Equal(
            $"H 100644 {Golden001CharlieOid} 0\tC.txt\0"
                + $"S 100644 {Golden001AlphaOid} 0\ta.txt\0"
                + $"H 100755 {Golden001RunOid} 0\tdir/run.sh\0"
                + $"H 120000 {Golden001LinkOid} 0\tlink\0"
                + $"M 100644 {Golden001BaseOid} 1\tm.txt\0"
                + $"M 100644 {Golden001OursOid} 2\tm.txt\0"
                + $"M 100644 {Golden001TheirsOid} 3\tm.txt\0"
                + $"H 100644 {Golden001ZetOid} 0\tž.txt\0",
            await LsFilesAsync(runner, repositoryPath)
        );
    }

    // -------------------------------------------------------- INDEX-GOLDEN-UNICODE-001

    private const string GoldenUnicode001 =
        "sha256:2675e7c20ddb3431d9d5f2b5e527833890bc7372f7ab920a0e1c2fd275c9bb97";

    // The same entries ordered by UTF-8 bytes instead (what canonical v2 is NOT).
    private const string GoldenUnicode001IfUtf8Ordered =
        "sha256:b598d96c2974bff6db46a5b6159ea63ac88653bf384c71f86522c088a6de8ea4";

    // SHA-256 and length of the raw `git ls-files --stage -z` bytes Git must write.
    private const string GoldenUnicode001RawLsFilesSha256 =
        "66f4aaae9c059bbc68a5dc79ef7daa599fe184074870ced0e5ad6ad6810faa76";

    private const int GoldenUnicode001RawLsFilesLength = 415;

    private const string Nfd = "e\u0301.txt"; // NFD: e + combining acute
    private const string Nfc = "\u00E9.txt"; // NFC: precomposed e-acute; a different file
    private const string BlackCat = "\U0001F408\u200D\u2B1B.txt"; // ZWJ sequence: three code points
    private const string VulcanSalute = "\U0001F596.txt"; // supplementary, below U+1F600
    private const string Grin = "\U0001F600.txt"; // supplementary: the trap partner
    private const string Rocket = "\U0001F680.txt"; // supplementary, above U+1F600
    private const string PrivateUse = "\uE000.txt"; // BMP above the surrogate range

    private static readonly (string Path, string Content, string Oid)[] GoldenUnicode001Entries =
    [
        (Nfd, "nfd\n", "60800a56cbd66a5b8ee8e1d373a9646949aa8d32"),
        (Nfc, "nfc\n", "7aef497efd4d33dc45bdbef862747021dbe632e1"),
        (BlackCat, "cat\n", "ef07ddcd0ae687cd8ac0728bf14d374b33df3926"),
        (VulcanSalute, "vulcan\n", "9f06c44cb1a7d243b47c1a5ad09fcc2db08b5a35"),
        (Grin, "grin\n", "c4c3dd29692a74817cd53bffdcb09f3214a3e3c6"),
        (Rocket, "rocket\n", "62b901d6ae28390a6c6f87dfeb723fcb25a4ea39"),
        (PrivateUse, "pua\n", "c3710fb860838eb43642a96e4dcd7360f227eebf"),
    ];

    [Fact]
    public void IndexGoldenUnicode001_CanonicalOrderIsUtf16Ordinal()
    {
        // Input in Git's UTF-8 byte order: U+E000 (EE 80 80) before the emoji (F0 ...).
        var utf8Order = new[] { Nfd, Nfc, PrivateUse, BlackCat, VulcanSalute, Grin, Rocket };

        Assert.Equal(
            utf8Order,
            GoldenUnicode001Entries
                .Select(entry => entry.Path)
                .OrderBy(path => Encoding.UTF8.GetBytes(path), ByteSequenceComparer.Instance)
                .ToArray()
        );

        var entries = utf8Order
            .Select(path => GoldenUnicode001Entries.Single(entry => entry.Path == path))
            .Select(entry => new GitIndexEntry("100644", entry.Oid, 0, entry.Path))
            .ToArray();

        var parts = GitIndexEntryCanonicalizer.Canonicalize(entries);

        // UTF-16 code units: the surrogate pairs (D83D ...) sort before U+E000.
        Assert.Equal(
            [Nfd, Nfc, BlackCat, VulcanSalute, Grin, Rocket, PrivateUse],
            parts.Where((_, index) => index % 4 == 3).ToArray()
        );

        Assert.Equal(GoldenUnicode001, ReferenceFingerprint(IndexDomain, parts));

        var utf8OrderedParts = entries.SelectMany(entry =>
            new[] { entry.Mode, entry.ObjectId, "0", entry.Path }
        );

        Assert.Equal(
            GoldenUnicode001IfUtf8Ordered,
            ReferenceFingerprint(IndexDomain, utf8OrderedParts)
        );
        Assert.NotEqual(GoldenUnicode001, GoldenUnicode001IfUtf8Ordered);
    }

    [Fact]
    public async Task IndexGoldenUnicode001_GitFixturePreservesPathsAndProducesExpectedIndexFingerprint()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            await InitializeSha1RepositoryAsync(runner, repositoryPath);

            foreach (var (path, content, _) in GoldenUnicode001Entries)
            {
                await File.WriteAllTextAsync(Path.Combine(repositoryPath, path), content);
            }

            await RunGitAsync(
                runner,
                repositoryPath,
                ["add", "--", .. GoldenUnicode001Entries.Select(entry => entry.Path)]
            );
            await CommitAsync(runner, repositoryPath, "unicode");

            // Git stored exactly these UTF-8 bytes (no normalization, no splitting).
            var raw = await ReadGitStandardOutputBytesAsync(
                runner,
                repositoryPath,
                "ls-files",
                "--stage",
                "-z"
            );

            Assert.Equal(GoldenUnicode001RawLsFilesLength, raw.Length);
            Assert.Equal(
                GoldenUnicode001RawLsFilesSha256,
                Convert.ToHexStringLower(SHA256.HashData(raw))
            );

            var result = await new GitSnapshotBuilder(runner).BuildAsync(repositoryPath);

            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.Equal(GoldenUnicode001, result.Snapshot!.IndexFingerprint);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    // ------------------------------------------------------------------ helpers

    // Test-side implementation of the canonical v2 framing, independent of
    // GitSnapshotBuilder; pinned to the Python reference values above.
    private static string ReferenceFingerprint(string domain, IEnumerable<string> parts)
    {
        using var buffer = new MemoryStream();
        var length = new byte[sizeof(uint)];

        foreach (var part in parts.Prepend(domain))
        {
            var bytes = Encoding.UTF8.GetBytes(part);

            BinaryPrimitives.WriteUInt32BigEndian(length, (uint)bytes.Length);
            buffer.Write(length);
            buffer.Write(bytes);
        }

        return "sha256:" + Convert.ToHexStringLower(SHA256.HashData(buffer.ToArray()));
    }

    private static async Task InitializeSha1RepositoryAsync(
        GitProcessRunner runner,
        string repositoryPath
    )
    {
        await RunGitAsync(
            runner,
            repositoryPath,
            "init",
            "-q",
            "--object-format=sha1",
            "-b",
            "main"
        );
        await RunGitAsync(runner, repositoryPath, "config", "core.autocrlf", "false");

        // Do not execute hooks inherited from global configuration or Git templates.
        var emptyHooksDirectory = Path.Combine(repositoryPath, ".git", "codelaxy-empty-hooks");
        Directory.CreateDirectory(emptyHooksDirectory);
        await RunGitAsync(runner, repositoryPath, "config", "core.hooksPath", emptyHooksDirectory);

        Assert.Equal(
            "sha1",
            (
                await RunGitReadAsync(runner, repositoryPath, "rev-parse", "--show-object-format")
            ).Trim()
        );
    }

    private static Task CommitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        string message
    ) =>
        RunGitAsync(
            runner,
            repositoryPath,
            "-c",
            "user.name=Codelaxy Tests",
            "-c",
            "user.email=codelaxy@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            message
        );

    private static Task<string> LsFilesAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] paths
    ) =>
        RunGitReadAsync(
            runner,
            repositoryPath,
            ["ls-files", "--stage", "-t", "-z", "--", .. paths]
        );

    private static async Task RunGitAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments
    )
    {
        var result = await runner.RunAsync(repositoryPath, arguments);

        Assert.True(result.Succeeded, $"git {string.Join(' ', arguments)}: {result.StandardError}");
    }

    private static async Task<string> RunGitReadAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments
    )
    {
        var result = await runner.RunReadOnlyAsync(repositoryPath, arguments, GitCommandTimeout);

        Assert.True(result.Succeeded, $"git {string.Join(' ', arguments)}: {result.StandardError}");

        return result.StandardOutput;
    }

    // Raw stdout bytes, bypassing the runner's UTF-8 decoding.
    private static async Task<byte[]> ReadGitStandardOutputBytesAsync(
        GitProcessRunner runner,
        string repositoryPath,
        params string[] arguments
    )
    {
        using var process = new Process
        {
            StartInfo = runner.CreateProcessStartInfo(repositoryPath, arguments, readOnly: true),
        };

        process.Start();
        process.StandardInput.Close();

        using var timeout = new CancellationTokenSource(GitCommandTimeout);
        await using var output = new MemoryStream();

        var copy = process.StandardOutput.BaseStream.CopyToAsync(output, timeout.Token);
        var error = process.StandardError.ReadToEndAsync(timeout.Token);
        var exited = process.WaitForExitAsync(timeout.Token);

        try
        {
            await Task.WhenAll(copy, error, exited);
        }
        catch (OperationCanceledException exception) when (timeout.IsCancellationRequested)
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }

            await process.WaitForExitAsync(CancellationToken.None);

            throw new TimeoutException(
                $"git {string.Join(' ', arguments)} timed out after {GitCommandTimeout}.",
                exception
            );
        }

        Assert.True(process.ExitCode == 0, $"git {string.Join(' ', arguments)}: {await error}");

        return output.ToArray();
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), $"Codelaxy Index Golden {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
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

    private sealed class ByteSequenceComparer : IComparer<byte[]>
    {
        public static readonly ByteSequenceComparer Instance = new();

        public int Compare(byte[]? x, byte[]? y) => x.AsSpan().SequenceCompareTo(y.AsSpan());
    }
}
