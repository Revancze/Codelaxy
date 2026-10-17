using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// Independent SHA-1/SHA-256 reference values, calculated with Python hashlib.
// Git object IDs were independently cross-checked with git hash-object.
public sealed class GitSnapshotHeadStagedGoldenTests
{
    private const string EmptyTreeOid = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";

    private const string CommitOid = "033b47f060080d50c84ae19aac859a29f0acbdd9";

    private const string StagedBlobOid = "19d9cc8584ac2c7dcf57d2680375e80f099dc481";

    private const string ExpectedH =
        "sha256:9fad891eb6f144d929d92ab8506785cee6c97bd0f319f4b21bd5fef8e171716a";

    private const string ExpectedEmptyI =
        "sha256:3115148de45a7df2c4ec15a03d1087c8c45b5ad925ce7082edc0a8bc0c32d843";

    private const string ExpectedEmptyS =
        "sha256:4b0df04c702d0a76cee09d268cb6febdb47732929cfa56cba2e7102d7377f06c";

    private const string ExpectedStagedI =
        "sha256:9fc24247be26865b5f96e2f221473562ad685a257053903eefb3c4c3895d813e";

    private const string ExpectedStagedS =
        "sha256:32ed2e0c6ce39cc4b51c240ebc3f73bbbdf55d4363f0975c965b6c177b9840e2";

    private const string CommitText =
        "tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\n"
        + "author Golden Tester <golden@example.invalid> 946684800 +0000\n"
        + "committer Golden Tester <golden@example.invalid> 946684800 +0000\n"
        + "\n"
        + "golden baseline\n";

    [Fact]
    public async Task HsGolden001_ProducesIndependentExpectedFingerprints()
    {
        var runner = new GitProcessRunner();
        var root = Path.Combine(Path.GetTempPath(), $"Codelaxy HS Golden {Guid.NewGuid():N}");

        Directory.CreateDirectory(root);

        try
        {
            // git init can execute reference-transaction hooks before local config exists.
            // Override inherited hooksPath for init itself, then persist it locally.
            var hooksDirectory = Path.Combine(root, ".git", "codelaxy-empty-hooks");

            await GitAsync(
                runner,
                root,
                "-c",
                $"core.hooksPath={hooksDirectory}",
                "init",
                "-q",
                "--object-format=sha1",
                "-b",
                "main"
            );

            Directory.CreateDirectory(hooksDirectory);

            await GitAsync(runner, root, "config", "core.hooksPath", hooksDirectory);

            await GitAsync(runner, root, "config", "core.autocrlf", "false");

            var gitDirectory = Path.Combine(root, ".git");

            await File.WriteAllBytesAsync(
                Path.Combine(gitDirectory, "empty-tree.bin"),
                Array.Empty<byte>()
            );

            Assert.Equal(
                EmptyTreeOid,
                await GitAsync(
                    runner,
                    root,
                    "hash-object",
                    "-w",
                    "-t",
                    "tree",
                    "--",
                    ".git/empty-tree.bin"
                )
            );

            await File.WriteAllTextAsync(
                Path.Combine(gitDirectory, "golden-commit.txt"),
                CommitText,
                Encoding.ASCII
            );

            Assert.Equal(
                CommitOid,
                await GitAsync(
                    runner,
                    root,
                    "hash-object",
                    "-w",
                    "-t",
                    "commit",
                    "--",
                    ".git/golden-commit.txt"
                )
            );

            await GitAsync(runner, root, "update-ref", "refs/heads/main", CommitOid);

            Assert.Equal(CommitOid, await GitAsync(runner, root, "rev-parse", "--verify", "HEAD"));

            var builder = new GitSnapshotBuilder(runner);
            var empty = await builder.BuildAsync(root);

            Assert.True(empty.Succeeded, empty.Diagnostic);
            Assert.NotNull(empty.Snapshot);
            Assert.Equal(ExpectedH, empty.Snapshot.HeadFingerprint);
            Assert.Equal(ExpectedEmptyI, empty.Snapshot.IndexFingerprint);
            Assert.Equal(ExpectedEmptyS, empty.Snapshot.StagedFingerprint);

            await File.WriteAllTextAsync(
                Path.Combine(root, "staged.txt"),
                "staged\n",
                new UTF8Encoding(false)
            );

            await GitAsync(runner, root, "add", "--", "staged.txt");

            Assert.Equal(
                StagedBlobOid,
                await GitAsync(runner, root, "hash-object", "--no-filters", "--", "staged.txt")
            );

            Assert.Equal(
                $"100644 {StagedBlobOid} 0\tstaged.txt",
                await GitAsync(runner, root, "ls-files", "--stage")
            );

            var staged = await builder.BuildAsync(root);

            Assert.True(staged.Succeeded, staged.Diagnostic);
            Assert.NotNull(staged.Snapshot);

            Assert.Equal(ExpectedH, staged.Snapshot.HeadFingerprint);
            Assert.Equal(ExpectedStagedI, staged.Snapshot.IndexFingerprint);
            Assert.Equal(ExpectedStagedS, staged.Snapshot.StagedFingerprint);

            Assert.Equal(empty.Snapshot.HeadFingerprint, staged.Snapshot.HeadFingerprint);

            Assert.NotEqual(empty.Snapshot.StagedFingerprint, staged.Snapshot.StagedFingerprint);
        }
        finally
        {
            foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
            {
                File.SetAttributes(file, FileAttributes.Normal);
            }

            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task<string> GitAsync(
        GitProcessRunner runner,
        string root,
        params string[] arguments
    )
    {
        var result = await runner.RunAsync(root, arguments, TimeSpan.FromSeconds(30));

        Assert.True(result.Succeeded, $"git {string.Join(' ', arguments)}: {result.StandardError}");

        return result.StandardOutput.TrimEnd('\r', '\n');
    }
}
