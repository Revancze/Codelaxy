using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

// F10: a path enumerated by `git ls-files --others` can disappear before
// GitSnapshotBuilder inspects it in the working tree. A test-owned Git proxy
// (tests/Codelaxy.F10GitProxy) captures Git's real -z output, deletes the
// enumerated file and only then hands the original output to the builder.
// Expected contract: no exception escapes BuildAsync, no snapshot is produced
// and the diagnostic reports a repository change during capture.
//
// What this test proves per platform (observed before the fix):
// - Linux: an unhandled FileNotFoundException escaped BuildAsync
//   (GetUntrackedRegularFileMode -> File.GetUnixFileMode). This is a real
//   fail-closed violation.
// - Windows: no exception and no snapshot were produced; the result was already
//   fail-closed. Only the diagnostic differed ("Unable to hash untracked files: ...")
//   because the vanished file surfaced later as a `git hash-object` failure.
//   On Windows this test therefore pins the diagnostic classification only.
[Collection("GitWrapperIsolation")]
public sealed class GitSnapshotVanishedUntrackedF10Tests
{
    [Theory]
    [InlineData("victim.txt")]
    [InlineData("name with spaces.txt")]
    [InlineData("příliš-žluťoučký-kůň.txt")]
    public async Task BuildAsync_ReturnsDiagnosticWhenEnumeratedUntrackedFileVanished(
        string victimName
    )
    {
        var root = CreateTestRoot();
        var repositoryPath = Path.Combine(root, "repository");
        var proxyDirectory = Path.Combine(root, "proxy");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, repositoryPath);

            var victimPath = Path.Combine(repositoryPath, victimName);
            await File.WriteAllTextAsync(victimPath, "F10 payload\n");

            // Positive control: the same repository is observable before the race.
            var baseline = await new GitSnapshotBuilder(realGit).BuildAsync(repositoryPath);
            Assert.True(baseline.Succeeded, baseline.Diagnostic);
            Assert.NotNull(baseline.Snapshot);

            var proxyExecutable = await DeployProxyAsync(realGit, proxyDirectory, victimName);
            var builder = new GitSnapshotBuilder(new GitProcessRunner(proxyExecutable));

            GitSnapshotBuildResult? observed = null;
            var exception = await Record.ExceptionAsync(async () =>
            {
                observed = await builder.BuildAsync(repositoryPath);
            });

            // Prove the trigger fired on the intended Git call with the real output.
            var hitPath = Path.Combine(proxyDirectory, "f10-hit.bin");
            Assert.True(File.Exists(hitPath), "The proxy did not intercept the enumeration.");
            Assert.Equal(
                victimName + "\0",
                Encoding.UTF8.GetString(await File.ReadAllBytesAsync(hitPath))
            );
            Assert.False(File.Exists(victimPath), "F10 victim file must be gone.");

            Assert.Null(exception);
            Assert.NotNull(observed);
            Assert.False(observed.Succeeded);
            Assert.Null(observed.Snapshot);
            Assert.Contains(
                "changed during snapshot capture",
                observed.Diagnostic,
                StringComparison.OrdinalIgnoreCase
            );
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    [Fact]
    public async Task Proxy_RefusesToTouchForeignRepository()
    {
        const string victimName = "victim.txt";
        var root = CreateTestRoot();
        var proxyDirectory = Path.Combine(root, "proxy");
        var foreignRepository = Path.Combine(root, "foreign-repository");

        try
        {
            var realGit = new GitProcessRunner();
            await InitializeRepositoryAsync(realGit, foreignRepository);

            var foreignVictim = Path.Combine(foreignRepository, victimName);
            await File.WriteAllTextAsync(foreignVictim, "must survive\n");

            var proxyExecutable = await DeployProxyAsync(realGit, proxyDirectory, victimName);

            var result = await new GitProcessRunner(proxyExecutable).RunReadOnlyAsync(
                foreignRepository,
                [
                    "-C",
                    foreignRepository,
                    "ls-files",
                    "--others",
                    "--exclude-per-directory=.gitignore",
                    "-z",
                ],
                TimeSpan.FromMinutes(2),
                CancellationToken.None
            );

            Assert.False(result.Succeeded);
            Assert.Contains(
                "F10 repository mismatch",
                result.StandardError,
                StringComparison.Ordinal
            );
            Assert.True(File.Exists(foreignVictim), "Proxy must not delete foreign files.");
            Assert.False(File.Exists(Path.Combine(proxyDirectory, "f10-hit.bin")));
        }
        finally
        {
            DeleteTestDirectory(root);
        }
    }

    private static string CreateTestRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), $"codelaxy-f10-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        return root;
    }

    private static async Task InitializeRepositoryAsync(GitProcessRunner git, string path)
    {
        Directory.CreateDirectory(path);
        await GoldenGitFixture.InitializeSha1Async(git, path);

        var commit = await git.RunAsync(
            path,
            [
                "-c",
                "user.name=Codelaxy Tests",
                "-c",
                "user.email=codelaxy@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "F10 baseline",
            ]
        );
        Assert.True(commit.Succeeded, commit.StandardError);
    }

    // Copies the proxy build output to a test-owned directory and writes the
    // configuration ONLY there, so no shared build output is ever armed.
    private static async Task<string> DeployProxyAsync(
        GitProcessRunner realGit,
        string proxyDirectory,
        string victimName
    )
    {
        var gitStartInfo = realGit.CreateProcessStartInfo(
            Path.GetTempPath(),
            ["--version"],
            readOnly: true
        );
        Assert.True(Path.IsPathFullyQualified(gitStartInfo.FileName));
        Assert.True(File.Exists(gitStartInfo.FileName));

        var outputDirectory = GetProxyOutputDirectory();
        Assert.True(Directory.Exists(outputDirectory), $"Proxy output missing: {outputDirectory}");

        Directory.CreateDirectory(proxyDirectory);

        foreach (var source in Directory.EnumerateFiles(outputDirectory, "Codelaxy.F10GitProxy*"))
        {
            File.Copy(source, Path.Combine(proxyDirectory, Path.GetFileName(source)));
        }

        var executable = Path.Combine(
            proxyDirectory,
            OperatingSystem.IsWindows() ? "Codelaxy.F10GitProxy.exe" : "Codelaxy.F10GitProxy"
        );
        Assert.True(File.Exists(executable), $"Proxy apphost missing: {executable}");

        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(
                executable,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
            );
        }

        await File.WriteAllLinesAsync(
            Path.Combine(proxyDirectory, "f10-git-proxy.conf"),
            [gitStartInfo.FileName, victimName]
        );

        return executable;
    }

    // Same layout rule as GitProcessRunnerTests.GetProcessTestHelperPath:
    // tests/<project>/bin/<host>/<configuration>/<tfm>.
    private static string GetProxyOutputDirectory()
    {
        var tfm = new DirectoryInfo(AppContext.BaseDirectory);
        var configuration = tfm.Parent!;
        var host = configuration.Parent!;
        var testsDirectory = host.Parent!.Parent!.Parent!;

        return Path.Combine(
            testsDirectory.FullName,
            "Codelaxy.F10GitProxy",
            "bin",
            host.Name,
            configuration.Name,
            tfm.Name
        );
    }

    private static void DeleteTestDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            return;
        }

        // Git object files are read-only on Windows.
        foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
        {
            File.SetAttributes(file, FileAttributes.Normal);
        }

        Directory.Delete(path, recursive: true);
    }
}
