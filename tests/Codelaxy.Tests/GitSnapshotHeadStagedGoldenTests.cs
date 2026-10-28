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
            await InitializeBaselineAsync(runner, root);

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

    // WORKTREE-GOLDEN-001: values derived by tests/golden_worktree_reference.py.
    // Only the worktree bytes change; HEAD and the staged index stay fixed.
    [Fact]
    public async Task WorktreeGolden001_ProducesIndependentExpectedFingerprints()
    {
        const string looseBlobOid = "b6586661e7ec0a4c9389276355d01e145861eb0c";
        const string changedBlobOid = "5ea2ed416fbd4a4cbe227b75fe255dd7fa6bd4d6";
        const string expectedInitialW =
            "sha256:880b5e1e7a55858c34a38bc049ce11a084852c7c457ad4ff59ef80201479089d";
        const string expectedChangedW =
            "sha256:05fff775479c003c230c208b60fa6b465e411a7f8e7027dcf18874a072a19b8c";

        var runner = new GitProcessRunner();
        var root = Path.Combine(Path.GetTempPath(), $"Codelaxy Worktree Golden {Guid.NewGuid():N}");
        Directory.CreateDirectory(root);

        try
        {
            await InitializeBaselineAsync(runner, root);
            await File.WriteAllTextAsync(
                Path.Combine(root, "staged.txt"),
                "staged\n",
                new UTF8Encoding(false)
            );
            await GitAsync(runner, root, "add", "--", "staged.txt");
            await File.WriteAllTextAsync(
                Path.Combine(root, "loose.txt"),
                "loose\n",
                new UTF8Encoding(false)
            );

            Assert.Equal(
                StagedBlobOid,
                await GitAsync(runner, root, "hash-object", "--no-filters", "--", "staged.txt")
            );
            Assert.Equal(
                looseBlobOid,
                await GitAsync(runner, root, "hash-object", "--no-filters", "--", "loose.txt")
            );
            var expectedIndex = $"100644 {StagedBlobOid} 0\tstaged.txt";
            Assert.Equal(expectedIndex, await GitAsync(runner, root, "ls-files", "--stage"));
            Assert.Equal(
                "loose.txt\0",
                await GitAsync(runner, root, "ls-files", "--others", "--exclude-standard", "-z")
            );

            var builder = new GitSnapshotBuilder(runner);
            var initial = await builder.BuildAsync(root);
            Assert.True(initial.Succeeded, initial.Diagnostic);
            Assert.NotNull(initial.Snapshot);
            Assert.Equal(ExpectedH, initial.Snapshot.HeadFingerprint);
            Assert.Equal(ExpectedStagedI, initial.Snapshot.IndexFingerprint);
            Assert.Equal(ExpectedStagedS, initial.Snapshot.StagedFingerprint);
            Assert.Equal(expectedInitialW, initial.Snapshot.WorkingTreeFingerprint);

            await File.WriteAllTextAsync(
                Path.Combine(root, "staged.txt"),
                "changed\n",
                new UTF8Encoding(false)
            );
            Assert.Equal(
                changedBlobOid,
                await GitAsync(runner, root, "hash-object", "--no-filters", "--", "staged.txt")
            );
            Assert.Equal(expectedIndex, await GitAsync(runner, root, "ls-files", "--stage"));
            Assert.Equal(CommitOid, await GitAsync(runner, root, "rev-parse", "--verify", "HEAD"));

            var changed = await builder.BuildAsync(root);
            Assert.True(changed.Succeeded, changed.Diagnostic);
            Assert.NotNull(changed.Snapshot);
            Assert.Equal(ExpectedH, changed.Snapshot.HeadFingerprint);
            Assert.Equal(ExpectedStagedI, changed.Snapshot.IndexFingerprint);
            Assert.Equal(ExpectedStagedS, changed.Snapshot.StagedFingerprint);
            Assert.Equal(expectedChangedW, changed.Snapshot.WorkingTreeFingerprint);
            Assert.NotEqual(
                initial.Snapshot.WorkingTreeFingerprint,
                changed.Snapshot.WorkingTreeFingerprint
            );
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

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task WorktreeGoldenF11_MultiplePathsKeepOidAttribution(bool tracked)
    {
        const string expectedTrackedI =
            "sha256:0938a02f94788084ce6957893b5c485178d86bb7725eb6cf2b69a3c4d18d7973";
        const string expectedTrackedS =
            "sha256:2a5539e74818aca17f6c381c990bde98171c35cb0cc8cf0b82127f6d2027f06a";
        const string expectedTrackedW =
            "sha256:23fd050198a17b12206d7ab1bb9c39ab17a8df2106b61f37d82cbaeeb7977897";
        const string expectedUntrackedW =
            "sha256:c08c07398df974ee8a5973e392a96df2512553bb211609f79b342b7ca531afc5";

        var runner = new GitProcessRunner();
        var root = Path.Combine(Path.GetTempPath(), $"Codelaxy F11 {Guid.NewGuid():N}");

        Directory.CreateDirectory(root);

        try
        {
            await InitializeBaselineAsync(runner, root);

            await File.WriteAllTextAsync(
                Path.Combine(root, "a.txt"),
                "alpha\n",
                new UTF8Encoding(false)
            );
            await File.WriteAllTextAsync(
                Path.Combine(root, "b.txt"),
                "charlie\n",
                new UTF8Encoding(false)
            );
            await File.WriteAllTextAsync(
                Path.Combine(root, "c.txt"),
                "bravo\n",
                new UTF8Encoding(false)
            );

            if (tracked)
            {
                await GitAsync(runner, root, "add", "--", "a.txt", "b.txt", "c.txt");
            }

            var result = await new GitSnapshotBuilder(runner).BuildAsync(root);

            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.NotNull(result.Snapshot);

            var snapshot = result.Snapshot;

            Assert.Equal(ExpectedH, snapshot.HeadFingerprint);

            Assert.Equal(tracked ? expectedTrackedI : ExpectedEmptyI, snapshot.IndexFingerprint);

            Assert.Equal(tracked ? expectedTrackedS : ExpectedEmptyS, snapshot.StagedFingerprint);

            Assert.Equal(
                tracked ? expectedTrackedW : expectedUntrackedW,
                snapshot.WorkingTreeFingerprint
            );
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

    [LinuxOnlyTheory]
    [InlineData("a.txt", "sha256:753ced1332e5fbe22d4ba06fb67b68eeb2280b6935898621e833baf642579f4d")]
    [InlineData("c.txt", "sha256:379d4d0fcf213bc3675488a157fb70717e140f4f5adbdcd5fde9bfdee6989643")]
    public async Task WorktreeGoldenF11_MixedUntrackedSymlinkKeepsOidAttribution(
        string linkTarget,
        string expectedW
    )
    {
        var runner = new GitProcessRunner();
        var root = Path.Combine(Path.GetTempPath(), $"Codelaxy F11 Mixed {Guid.NewGuid():N}");

        Directory.CreateDirectory(root);

        try
        {
            await InitializeBaselineAsync(runner, root);

            await File.WriteAllTextAsync(
                Path.Combine(root, "a.txt"),
                "alpha\n",
                new UTF8Encoding(false)
            );

            await File.WriteAllTextAsync(
                Path.Combine(root, "c.txt"),
                "bravo\n",
                new UTF8Encoding(false)
            );

            var linkPath = Path.Combine(root, "b.link");

            File.CreateSymbolicLink(linkPath, linkTarget);

            Assert.Equal(linkTarget, new FileInfo(linkPath).LinkTarget);

            var result = await new GitSnapshotBuilder(runner).BuildAsync(root);

            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.NotNull(result.Snapshot);

            var snapshot = result.Snapshot;

            Assert.Equal(ExpectedH, snapshot.HeadFingerprint);
            Assert.Equal(ExpectedEmptyI, snapshot.IndexFingerprint);
            Assert.Equal(ExpectedEmptyS, snapshot.StagedFingerprint);
            Assert.Equal(expectedW, snapshot.WorkingTreeFingerprint);
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

    [Theory]
    [InlineData(false, "sha256:7746826a6606ab10bbbd6c47d4d34d69862c02836e41ee6f210321e22d659f4b")]
    [InlineData(true, "sha256:91227ae363aa7ae7bb48791bbcd665bd3b2bc43e75ca98ec563674ce3afcb289")]
    public async Task WorktreeGoldenF11_MixedTrackedStatesKeepOidAttribution(
        bool directoryConflict,
        string expectedW
    )
    {
        const string expectedI =
            "sha256:0938a02f94788084ce6957893b5c485178d86bb7725eb6cf2b69a3c4d18d7973";
        const string expectedS =
            "sha256:2a5539e74818aca17f6c381c990bde98171c35cb0cc8cf0b82127f6d2027f06a";

        var runner = new GitProcessRunner();
        var root = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy F11 Tracked Mixed {Guid.NewGuid():N}"
        );

        Directory.CreateDirectory(root);

        try
        {
            await InitializeBaselineAsync(runner, root);

            await File.WriteAllTextAsync(
                Path.Combine(root, "a.txt"),
                "alpha\n",
                new UTF8Encoding(false)
            );

            var middlePath = Path.Combine(root, "b.txt");

            await File.WriteAllTextAsync(middlePath, "charlie\n", new UTF8Encoding(false));

            await File.WriteAllTextAsync(
                Path.Combine(root, "c.txt"),
                "bravo\n",
                new UTF8Encoding(false)
            );

            await GitAsync(runner, root, "add", "--", "a.txt", "b.txt", "c.txt");

            // Keep b.txt in the index but exclude it
            // from regular working-tree hashing.
            File.Delete(middlePath);

            if (directoryConflict)
            {
                Directory.CreateDirectory(middlePath);
            }

            Assert.False(File.Exists(middlePath));
            Assert.Equal(directoryConflict, Directory.Exists(middlePath));

            var result = await new GitSnapshotBuilder(runner).BuildAsync(root);

            Assert.True(result.Succeeded, result.Diagnostic);
            Assert.NotNull(result.Snapshot);

            var snapshot = result.Snapshot;

            Assert.Equal(ExpectedH, snapshot.HeadFingerprint);
            Assert.Equal(expectedI, snapshot.IndexFingerprint);
            Assert.Equal(expectedS, snapshot.StagedFingerprint);
            Assert.Equal(expectedW, snapshot.WorkingTreeFingerprint);
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

    private static async Task InitializeBaselineAsync(GitProcessRunner runner, string root)
    {
        await GoldenGitFixture.InitializeSha1Async(runner, root);

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
