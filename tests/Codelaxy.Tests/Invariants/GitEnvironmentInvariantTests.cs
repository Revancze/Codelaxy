using Codelaxy.Git;

namespace Codelaxy.Tests;

[CollectionDefinition("Git environment", DisableParallelization = true)]
public sealed class GitEnvironmentCollection;

[Collection("Git environment")]
public class GitEnvironmentIsolationTests
{
    [Fact]
    public async Task RunAsync_IgnoresInheritedGitDir()
    {
        await AssertVariableIsIgnoredAsync(
            "GIT_DIR",
            ["rev-parse", "--git-dir"]);
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitWorkTree()
    {
        await AssertVariableIsIgnoredAsync(
            "GIT_WORK_TREE",
            ["rev-parse", "--show-toplevel"]);
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitCommonDir()
    {
        await AssertVariableIsIgnoredAsync(
            "GIT_COMMON_DIR",
            ["rev-parse", "--git-common-dir"]);
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitIndexFile()
    {
        await AssertVariableIsIgnoredAsync(
            "GIT_INDEX_FILE",
            ["rev-parse", "--git-path", "index"]);
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitConfigCount()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        var originalCount =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_COUNT");

        var originalKey =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_KEY_0");

        var originalValue =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_VALUE_0");

        var originalParameters =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_PARAMETERS");

        try
        {
            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_PARAMETERS",
                null);

            var initResult =
                await runner.RunAsync(
                    repositoryPath,
                    ["init"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            var configureResult =
                await runner.RunAsync(
                    repositoryPath,
                    [
                        "config",
                        "status.renames",
                        "true"
                    ]);

            Assert.True(
                configureResult.Succeeded,
                configureResult.StandardError);

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_COUNT",
                "1");

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_KEY_0",
                "status.renames");

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_VALUE_0",
                "false");

            var result =
                await runner.RunAsync(
                    repositoryPath,
                    [
                        "config",
                        "--get",
                        "status.renames"
                    ]);

            Assert.True(
                result.Succeeded,
                result.StandardError);

            Assert.Equal(
                "true",
                result.StandardOutput.Trim());
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_COUNT",
                originalCount);

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_KEY_0",
                originalKey);

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_VALUE_0",
                originalValue);

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_PARAMETERS",
                originalParameters);

            Directory.Delete(
                repositoryPath,
                recursive: true);
        }
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitConfigParameters()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        var originalParameters =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_PARAMETERS");

        var originalCount =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_COUNT");

        try
        {
            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_COUNT",
                null);

            var initResult =
                await runner.RunAsync(
                    repositoryPath,
                    ["init"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            var configureResult =
                await runner.RunAsync(
                    repositoryPath,
                    [
                        "config",
                        "status.renames",
                        "true"
                    ]);

            Assert.True(
                configureResult.Succeeded,
                configureResult.StandardError);

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_PARAMETERS",
                "'status.renames=false'");

            var result =
                await runner.RunAsync(
                    repositoryPath,
                    [
                        "config",
                        "--get",
                        "status.renames"
                    ]);

            Assert.True(
                result.Succeeded,
                result.StandardError);

            Assert.Equal(
                "true",
                result.StandardOutput.Trim());
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_PARAMETERS",
                originalParameters);

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_COUNT",
                originalCount);

            Directory.Delete(
                repositoryPath,
                recursive: true);
        }
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitConfigGlobal()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        var originalGlobal =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_GLOBAL");

        var poisonMarker =
            $"CODELAXY_POISON_{Guid.NewGuid():N}";

        var safeMarker =
            $"CODELAXY_SAFE_{Guid.NewGuid():N}";

        var poisonConfigPath =
            Path.Combine(
                repositoryPath,
                "poison-global.gitconfig");

        try
        {
            var initResult =
                await runner.RunAsync(
                    repositoryPath,
                    ["init"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            var configureResult =
                await runner.RunAsync(
                    repositoryPath,
                    [
                        "config",
                        "codelaxy.safe",
                        safeMarker
                    ]);

            Assert.True(
                configureResult.Succeeded,
                configureResult.StandardError);

            await File.WriteAllTextAsync(
                poisonConfigPath,
                $"[codelaxy]\n\tpoison = {poisonMarker}\n");

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_GLOBAL",
                poisonConfigPath);

            var result =
                await runner.RunAsync(
                    repositoryPath,
                    [
                        "config",
                        "--list"
                    ]);

            Assert.True(
                result.Succeeded,
                result.StandardError);

            Assert.Contains(
                safeMarker,
                result.StandardOutput,
                StringComparison.Ordinal);

            Assert.DoesNotContain(
                poisonMarker,
                result.StandardOutput,
                StringComparison.Ordinal);
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_GLOBAL",
                originalGlobal);

            Directory.Delete(
                repositoryPath,
                recursive: true);
        }
    }

    [Fact]
    public async Task RunAsync_IgnoresInheritedGitConfigSystem()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        var originalSystem =
            Environment.GetEnvironmentVariable(
                "GIT_CONFIG_SYSTEM");

        var variableName =
            $"poison{Guid.NewGuid():N}";

        var configKey =
            $"codelaxy.{variableName}";

        var poisonMarker =
            $"CODELAXY_POISON_{Guid.NewGuid():N}";

        var poisonConfigPath =
            Path.Combine(
                repositoryPath,
                "poison-system.gitconfig");

        try
        {
            var initResult =
                await runner.RunAsync(
                    repositoryPath,
                    ["init"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            await File.WriteAllTextAsync(
                poisonConfigPath,
                $"[codelaxy]\n\t{variableName} = {poisonMarker}\n");

            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_SYSTEM",
                poisonConfigPath);

            var result =
                await runner.RunAsync(
                    repositoryPath,
                    [
                        "config",
                        "--get",
                        configKey
                    ]);

            Assert.False(result.Succeeded);

            Assert.DoesNotContain(
                poisonMarker,
                result.StandardOutput,
                StringComparison.Ordinal);

            Assert.DoesNotContain(
                poisonMarker,
                result.StandardError,
                StringComparison.Ordinal);
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                "GIT_CONFIG_SYSTEM",
                originalSystem);

            Directory.Delete(
                repositoryPath,
                recursive: true);
        }
    }

    private static async Task AssertVariableIsIgnoredAsync(
        string variableName,
        IEnumerable<string> arguments)
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        var originalValue =
            Environment.GetEnvironmentVariable(
                variableName);

        var poisonMarker =
            $"CODELAXY_POISON_{Guid.NewGuid():N}";

        var poisonPath =
            Path.Combine(
                repositoryPath,
                poisonMarker);

        try
        {
            var initResult =
                await runner.RunAsync(
                    repositoryPath,
                    ["init"]);

            Assert.True(
                initResult.Succeeded,
                initResult.StandardError);

            Environment.SetEnvironmentVariable(
                variableName,
                poisonPath);

            var result =
                await runner.RunAsync(
                    repositoryPath,
                    arguments);

            Assert.True(
                result.Succeeded,
                result.StandardError);

            Assert.DoesNotContain(
                poisonMarker,
                result.StandardOutput,
                StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                variableName,
                originalValue);

            Directory.Delete(
                repositoryPath,
                recursive: true);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        var path =
            Path.Combine(
                Path.GetTempPath(),
                $"Codelaxy Git Env Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }
}