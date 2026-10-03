using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitRepositoryStateTests
{
    [Fact]
    public async Task ReadAsync_ReturnsRepositoryState()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(repositoryPath, ["init", "-b", "main"]);

            Assert.True(initResult.Succeeded, initResult.StandardError);

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "README.md"), "# test");

            var addResult = await runner.RunAsync(repositoryPath, ["add", "README.md"]);

            Assert.True(addResult.Succeeded, addResult.StandardError);

            var commitResult = await runner.RunAsync(
                repositoryPath,
                [
                    "-c",
                    "user.name=Codelaxy Tests",
                    "-c",
                    "user.email=codelaxy@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ]
            );

            Assert.True(commitResult.Succeeded, commitResult.StandardError);

            var expectedHead = await runner.RunAsync(repositoryPath, ["rev-parse", "HEAD"]);

            Assert.True(expectedHead.Succeeded, expectedHead.StandardError);

            var reader = new GitRepositoryStateReader(runner);

            var state = await reader.ReadAsync(repositoryPath);

            Assert.Equal(expectedHead.StandardOutput.Trim(), state.Head);

            Assert.Equal("main", state.Branch);
            Assert.True(state.IsInsideWorkTree);
            Assert.False(state.IsBare);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    [Fact]
    public async Task ReadAsync_ReturnsNullBranchWhenHeadIsDetached()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(repositoryPath, ["init", "-b", "main"]);

            Assert.True(initResult.Succeeded, initResult.StandardError);

            await File.WriteAllTextAsync(Path.Combine(repositoryPath, "README.md"), "# test");

            var addResult = await runner.RunAsync(repositoryPath, ["add", "README.md"]);

            Assert.True(addResult.Succeeded, addResult.StandardError);

            var commitResult = await runner.RunAsync(
                repositoryPath,
                [
                    "-c",
                    "user.name=Codelaxy Tests",
                    "-c",
                    "user.email=codelaxy@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ]
            );

            Assert.True(commitResult.Succeeded, commitResult.StandardError);

            var expectedHead = await runner.RunAsync(repositoryPath, ["rev-parse", "HEAD"]);

            Assert.True(expectedHead.Succeeded, expectedHead.StandardError);

            var detachResult = await runner.RunAsync(
                repositoryPath,
                ["checkout", "--detach", "HEAD"]
            );

            Assert.True(detachResult.Succeeded, detachResult.StandardError);

            var reader = new GitRepositoryStateReader(runner);

            var state = await reader.ReadAsync(repositoryPath);

            Assert.Equal(expectedHead.StandardOutput.Trim(), state.Head);

            Assert.Null(state.Branch);
            Assert.True(state.IsInsideWorkTree);
            Assert.False(state.IsBare);
        }
        finally
        {
            DeleteDirectory(repositoryPath);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), $"Codelaxy State Tests {Guid.NewGuid():N}");

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

        foreach (
            var directory in Directory.EnumerateDirectories(path, "*", SearchOption.AllDirectories)
        )
        {
            File.SetAttributes(directory, FileAttributes.Normal);
        }

        File.SetAttributes(path, FileAttributes.Normal);

        Directory.Delete(path, recursive: true);
    }
}
