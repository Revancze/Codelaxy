using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

public sealed class GitObjectHasherTests
{
    [Theory]
    [InlineData("zero\0byte.txt")]
    [InlineData("")]
    public void TryEncodePaths_RejectsUnsupportedNames(string path)
    {
        var succeeded = GitObjectHasher.TryEncodePaths([path], out var input, out var diagnostic);

        Assert.False(succeeded);
        Assert.Empty(input);
        Assert.NotEmpty(diagnostic);
    }

    [Fact]
    public void TryEncodePaths_EscapesSpecialCharacters()
    {
        var succeeded = GitObjectHasher.TryEncodePaths(
            ["a b\\c.txt"],
            out var input,
            out var diagnostic
        );

        Assert.True(succeeded, diagnostic);

        var expected = Encoding.UTF8.GetBytes("\"a\\040b\\134c.txt\"\n");

        Assert.Equal(expected, input);
    }

    [Fact]
    public void TryParseObjectIds_AcceptsValidHashes()
    {
        foreach (var length in new[] { 40, 64 })
        {
            var oid = new string('a', length);

            var succeeded = GitObjectHasher.TryParseObjectIds(oid + "\n", 1, out var objectIds);

            Assert.True(succeeded);
            Assert.Equal([oid], objectIds);
        }
    }

    [Fact]
    public void TryParseObjectIds_RejectsMalformedHashes()
    {
        var valid = new string('a', 40);

        var malformed = new[]
        {
            "",
            "abcd\n",
            valid + "\n" + valid + "\n",
            new string('a', 39) + "g\n",
            valid.ToUpperInvariant() + "\n",
            valid + "\r\n",
            valid + "\n\n",
        };

        foreach (var output in malformed)
        {
            Assert.False(
                GitObjectHasher.TryParseObjectIds(output, 1, out _),
                $"Invalid output was accepted: {output}"
            );
        }
    }

    [Fact]
    public void TryParseObjectIds_RejectsMixedLengths()
    {
        var sha1 = new string('a', 40);
        var sha256 = new string('b', 64);

        Assert.False(GitObjectHasher.TryParseObjectIds($"{sha1}\n{sha256}\n", 2, out _));

        Assert.False(GitObjectHasher.TryParseObjectIds($"{sha256}\n{sha1}\n", 2, out _));
    }

    [Fact]
    public async Task StdinPaths_ReturnsSameObjectIdsAsIndividualGitCommands()
    {
        var runner = new GitProcessRunner();
        var root = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy F1 Hash Equivalence {Guid.NewGuid():N}"
        );

        Directory.CreateDirectory(root);

        try
        {
            var init = await runner.RunAsync(root, ["init", "-b", "main"]);
            Assert.True(init.Succeeded, init.StandardError);

            var names = new List<string>
            {
                "ordinary.txt",
                "with space.txt",
                "-leading-dash.txt",
                "český-soubor.txt",
                "日本語.txt",
                "emoji-\U0001F600.txt",
            };

            if (!OperatingSystem.IsWindows())
            {
                names.Add("\"leading-quote.txt");
                names.Add("back\\slash.txt");
                names.Add("tab\tname.txt");
            }

            foreach (var name in names)
            {
                await File.WriteAllTextAsync(
                    Path.Combine(root, name),
                    "unique content: " + name + "\n"
                );
            }

            var encoded = GitObjectHasher.TryEncodePaths(names, out var input, out var diagnostic);

            Assert.True(encoded, diagnostic);

            var batch = await runner.RunReadOnlyAsync(
                root,
                ["hash-object", "--no-filters", "--stdin-paths"],
                TimeSpan.FromSeconds(30),
                input
            );

            Assert.True(batch.Succeeded, batch.StandardError);

            Assert.True(
                GitObjectHasher.TryParseObjectIds(
                    batch.StandardOutput,
                    names.Count,
                    out var objectIds
                )
            );

            for (var index = 0; index < names.Count; index++)
            {
                var direct = await runner.RunReadOnlyAsync(
                    root,
                    ["hash-object", "--no-filters", "--", names[index]],
                    TimeSpan.FromSeconds(30)
                );

                Assert.True(direct.Succeeded, direct.StandardError);
                Assert.Equal(direct.StandardOutput.Trim(), objectIds[index]);
            }
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void TryEncodePaths_EncodesLineFeedWithGitOctalEscape()
    {
        var succeeded = GitObjectHasher.TryEncodePaths(
            ["line\nbreak.txt"],
            out var input,
            out var diagnostic
        );

        Assert.True(succeeded, diagnostic);

        Assert.Equal(System.Text.Encoding.UTF8.GetBytes("\"line\\012break.txt\"\n"), input);
    }

    [Fact]
    public void TryEncodePaths_EncodesRealEmojiAsUtf8Octal()
    {
        var succeeded = GitObjectHasher.TryEncodePaths(
            ["emoji-\U0001F600.txt"],
            out var input,
            out var diagnostic
        );

        Assert.True(succeeded, diagnostic);

        var expected = System.Text.Encoding.ASCII.GetBytes("\"emoji-\\360\\237\\230\\200.txt\"\n");

        Assert.Equal(expected, input);
    }
}
