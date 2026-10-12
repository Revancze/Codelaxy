using Codelaxy.Git;

namespace Codelaxy.Tests;

public class WindowsFileIdentityTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void TryRead_RecognizesWindowsAliases(bool directory)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var root = Path.Combine(Path.GetTempPath(), $"Codelaxy Identity {Guid.NewGuid():N}");

        try
        {
            var bin = Path.Combine(root, "repo", "bin");
            var outside = Path.Combine(root, "outside");

            Directory.CreateDirectory(bin);
            Directory.CreateDirectory(outside);

            var git = Path.Combine(bin, "git.exe");
            File.WriteAllText(git, "Identity test only");

            var other = Path.Combine(outside, "other.exe");
            File.WriteAllText(other, "Different file");

            var target = directory ? bin : git;
            var different = directory ? outside : other;

            Assert.True(WindowsFileIdentity.TryRead(target, out var expected));
            Assert.True(WindowsFileIdentity.TryRead(different, out var otherId));
            Assert.NotEqual(expected, otherId);

            Assert.Equal(':', target[1]);

            var unc = $@"\\localhost\{char.ToUpperInvariant(target[0])}$" + target[2..];

            var aliases = new[] { @"\\?\" + target, @"\\.\" + target, unc, @"\\?\UNC\" + unc[2..] };

            foreach (var alias in aliases)
            {
                Assert.True(
                    directory ? Directory.Exists(alias) : File.Exists(alias),
                    $"Test alias is inaccessible: '{alias}'."
                );

                Assert.True(
                    WindowsFileIdentity.TryRead(alias, out var actual),
                    $"Unable to read filesystem identity: '{alias}'."
                );

                Assert.Equal(expected, actual);
            }
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }
}
