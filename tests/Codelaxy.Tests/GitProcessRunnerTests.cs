using System.Diagnostics;
using System.Text;
using Codelaxy.Git;

namespace Codelaxy.Tests;

public class GitProcessRunnerTests
{
    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromSeconds(30);

    [Fact]
    public async Task RunAsync_CanExecuteGit()
    {
        var runner = new GitProcessRunner();

        var result = await runner.RunAsync(Directory.GetCurrentDirectory(), ["--version"]);

        Assert.True(result.Succeeded);
        Assert.Equal(0, result.ExitCode);
        Assert.StartsWith("git version ", result.StandardOutput);
        Assert.True(string.IsNullOrWhiteSpace(result.StandardError));
    }

    [Fact]
    public async Task RunAsync_UsesRequestedWorkingDirectory()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(repositoryPath, ["init"]);

            Assert.True(initResult.Succeeded);

            var nestedPath = Path.Combine(repositoryPath, "directory with spaces");

            Directory.CreateDirectory(nestedPath);

            var result = await runner.RunAsync(nestedPath, ["rev-parse", "--show-prefix"]);

            Assert.True(result.Succeeded);

            var actualPrefix = result.StandardOutput.Trim().Replace('\\', '/');

            Assert.Equal("directory with spaces/", actualPrefix);
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
        }
    }

    [Fact]
    public void CreateProcessStartInfo_PinsRedirectedGitOutputToUtf8()
    {
        var runner = new GitProcessRunner();

        var startInfo = runner.CreateProcessStartInfo(
            Environment.CurrentDirectory,
            ["status", "--short"],
            readOnly: true
        );

        Assert.All(
            new[] { startInfo.StandardOutputEncoding, startInfo.StandardErrorEncoding },
            encoding => Assert.Equal(System.Text.Encoding.UTF8.CodePage, encoding?.CodePage)
        );
    }

    [Fact]
    public void CreateProcessStartInfo_DisablesInteractiveInput()
    {
        var runner = new GitProcessRunner();

        var startInfo = runner.CreateProcessStartInfo(
            Environment.CurrentDirectory,
            ["status", "--short"],
            readOnly: true
        );

        Assert.True(startInfo.RedirectStandardInput);

        Assert.Equal("0", startInfo.Environment["GIT_TERMINAL_PROMPT"]);
    }

    [Fact]
    public async Task RunReadOnlyAsync_ClosesStandardInput()
    {
        var runner = new GitProcessRunner("dotnet");

        var helperPath = GetProcessTestHelperPath();

        Assert.True(File.Exists(helperPath), $"Process test helper not found: {helperPath}");

        var result = await runner.RunReadOnlyAsync(
            Directory.GetCurrentDirectory(),
            [helperPath, "read-stdin"],
            TimeSpan.FromSeconds(5)
        );

        Assert.True(result.Succeeded, result.StandardError);

        Assert.Equal("EOF", result.StandardOutput);
    }

    [Fact]
    public async Task RunReadOnlyAsync_DisablesTerminalPrompt()
    {
        var runner = new GitProcessRunner("dotnet");

        var helperPath = GetProcessTestHelperPath();

        Assert.True(File.Exists(helperPath), $"Process test helper not found: {helperPath}");

        var result = await runner.RunReadOnlyAsync(
            Directory.GetCurrentDirectory(),
            [helperPath, "print-env", "GIT_TERMINAL_PROMPT"],
            TimeSpan.FromSeconds(5)
        );

        Assert.True(result.Succeeded, result.StandardError);

        Assert.Equal("0", result.StandardOutput);
    }

    [Fact]
    public async Task RunAsync_PreservesArgumentContainingSpaces()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(repositoryPath, ["init"]);

            Assert.True(initResult.Succeeded);

            var setResult = await runner.RunAsync(
                repositoryPath,
                ["config", "--local", "codelaxy.test", "value with spaces"]
            );

            Assert.True(setResult.Succeeded);

            var getResult = await runner.RunAsync(
                repositoryPath,
                ["config", "--local", "--get", "codelaxy.test"]
            );

            Assert.True(getResult.Succeeded);

            Assert.Equal("value with spaces", getResult.StandardOutput.Trim());
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
        }
    }

    [Fact]
    public async Task RunAsync_ReturnsFailureWithoutThrowing()
    {
        var runner = new GitProcessRunner();

        var result = await runner.RunAsync(
            Directory.GetCurrentDirectory(),
            ["codelaxy-command-that-does-not-exist"]
        );

        Assert.False(result.Succeeded);
        Assert.NotEqual(0, result.ExitCode);
        Assert.False(string.IsNullOrWhiteSpace(result.StandardError));
    }

    [Fact]
    public async Task RunAsync_ReturnsLaunchFailureWhenGitCannotBeStarted()
    {
        var runner = new GitProcessRunner("codelaxy-git-executable-that-does-not-exist");

        var result = await runner.RunAsync(Directory.GetCurrentDirectory(), ["--version"]);

        Assert.False(result.Started);
        Assert.Null(result.ExitCode);
        Assert.Equal(GitCommandFailureKind.LaunchFailure, result.FailureKind);
        Assert.False(result.Succeeded);
    }

    [Fact]
    public async Task RunAsync_DoesNotStartProcessWhenAlreadyCancelled()
    {
        var runner = new GitProcessRunner("codelaxy-git-executable-that-does-not-exist");

        using var cancellation = new CancellationTokenSource();

        cancellation.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            runner.RunAsync(Directory.GetCurrentDirectory(), ["--version"], cancellation.Token)
        );
    }

    [Fact]
    public async Task RunAsync_KillsStartedProcessWhenCancelled()
    {
        var runner = new GitProcessRunner("dotnet");

        var helperPath = GetProcessTestHelperPath();

        Assert.True(File.Exists(helperPath), $"Process test helper not found: {helperPath}");

        var pidFile = Path.Combine(Path.GetTempPath(), $"Codelaxy Process {Guid.NewGuid():N}.pid");

        using var cancellation = new CancellationTokenSource();

        Process? helperProcess = null;

        try
        {
            var runTask = runner.RunAsync(
                Directory.GetCurrentDirectory(),
                [helperPath, pidFile],
                cancellation.Token
            );

            using var startTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));

            while (!File.Exists(pidFile))
            {
                await Task.Delay(20, startTimeout.Token);
            }

            var processId = int.Parse(await File.ReadAllTextAsync(pidFile, startTimeout.Token));

            helperProcess = Process.GetProcessById(processId);

            cancellation.Cancel();

            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => runTask);

            var exitTask = helperProcess.WaitForExitAsync();

            var completedTask = await Task.WhenAny(exitTask, Task.Delay(TimeSpan.FromSeconds(2)));

            Assert.Same(exitTask, completedTask);
        }
        finally
        {
            cancellation.Cancel();

            if (helperProcess is not null)
            {
                try
                {
                    if (!helperProcess.HasExited)
                    {
                        helperProcess.Kill(entireProcessTree: true);

                        await helperProcess.WaitForExitAsync();
                    }
                }
                catch (InvalidOperationException)
                {
                    // Process exited between HasExited and Kill.
                }

                helperProcess.Dispose();
            }

            if (File.Exists(pidFile))
            {
                File.Delete(pidFile);
            }
        }
    }

    [Fact]
    public async Task RunAsync_ReportsTimeoutAndKillsProcess()
    {
        var runner = new GitProcessRunner("dotnet");

        var helperPath = GetProcessTestHelperPath();

        Assert.True(File.Exists(helperPath), $"Process test helper not found: {helperPath}");

        var pidFile = Path.Combine(Path.GetTempPath(), $"Codelaxy Timeout {Guid.NewGuid():N}.pid");

        Process? helperProcess = null;

        try
        {
            var runTask = runner.RunAsync(
                Directory.GetCurrentDirectory(),
                [helperPath, pidFile],
                TimeSpan.FromSeconds(2)
            );

            using var startTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));

            var processId = await WaitForProcessIdAsync(pidFile, startTimeout.Token);

            try
            {
                helperProcess = Process.GetProcessById(processId);
            }
            catch (ArgumentException)
            {
                // The timed-out process already exited.
            }

            var result = await runTask;

            Assert.Equal(GitCommandFailureKind.Timeout, result.FailureKind);

            if (helperProcess is not null)
            {
                await helperProcess.WaitForExitAsync(startTimeout.Token);

                Assert.True(helperProcess.HasExited);
            }
        }
        finally
        {
            if (helperProcess is not null)
            {
                try
                {
                    if (!helperProcess.HasExited)
                    {
                        helperProcess.Kill(entireProcessTree: true);

                        await helperProcess.WaitForExitAsync();
                    }
                }
                catch (InvalidOperationException) { }

                helperProcess.Dispose();
            }

            if (File.Exists(pidFile))
            {
                File.Delete(pidFile);
            }
        }
    }

    [Fact]
    public async Task RunReadOnlyAsync_ReportsTimeoutAndKillsProcess()
    {
        var runner = new GitProcessRunner("dotnet");

        var helperPath = GetProcessTestHelperPath();

        Assert.True(File.Exists(helperPath), $"Process test helper not found: {helperPath}");

        var pidFile = Path.Combine(
            Path.GetTempPath(),
            $"Codelaxy ReadOnly Timeout {Guid.NewGuid():N}.pid"
        );

        Process? helperProcess = null;

        try
        {
            var runTask = runner.RunReadOnlyAsync(
                Directory.GetCurrentDirectory(),
                [helperPath, pidFile],
                TimeSpan.FromSeconds(2)
            );

            using var startTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));

            var processId = await WaitForProcessIdAsync(pidFile, startTimeout.Token);

            try
            {
                helperProcess = Process.GetProcessById(processId);
            }
            catch (ArgumentException)
            {
                // The timed-out process already exited.
            }

            var result = await runTask;

            Assert.Equal(GitCommandFailureKind.Timeout, result.FailureKind);

            if (helperProcess is not null)
            {
                await helperProcess.WaitForExitAsync(startTimeout.Token);

                Assert.True(helperProcess.HasExited);
            }
        }
        finally
        {
            if (helperProcess is not null)
            {
                try
                {
                    if (!helperProcess.HasExited)
                    {
                        helperProcess.Kill(entireProcessTree: true);

                        await helperProcess.WaitForExitAsync();
                    }
                }
                catch (InvalidOperationException)
                {
                    // Process exited between HasExited and Kill.
                }

                helperProcess.Dispose();
            }

            if (File.Exists(pidFile))
            {
                File.Delete(pidFile);
            }
        }
    }

    [Fact]
    public async Task RunReadOnlyAsync_WritesStandardInputPayloadAndClosesInput()
    {
        var runner = new GitProcessRunner();
        var repositoryPath = CreateTemporaryDirectory();

        try
        {
            var initResult = await runner.RunAsync(
                repositoryPath,
                ["init", "--object-format=sha1"]
            );

            Assert.True(initResult.Succeeded, initResult.StandardError);

            var result = await runner.RunReadOnlyAsync(
                repositoryPath,
                ["hash-object", "--stdin"],
                TimeSpan.FromSeconds(30),
                Encoding.UTF8.GetBytes("codelaxy stdin payload\n")
            );

            Assert.True(result.Succeeded, result.StandardError);

            Assert.Equal("a2e78ef8f87fd57cbb1064b20dbad30499be7d00", result.StandardOutput.Trim());
        }
        finally
        {
            Directory.Delete(repositoryPath, recursive: true);
        }
    }

    [Fact]
    public void RunReadOnlyAsync_RequiresTimeout()
    {
        var methods = typeof(GitProcessRunner)
            .GetMethods()
            .Where(method => method.Name == nameof(GitProcessRunner.RunReadOnlyAsync))
            .ToArray();

        Assert.NotEmpty(methods);

        foreach (var method in methods)
        {
            var parameters = method.GetParameters();

            var timeoutParameter = Assert.Single(
                parameters,
                parameter => parameter.ParameterType == typeof(TimeSpan)
            );

            Assert.False(timeoutParameter.HasDefaultValue);
        }
    }

    [Fact]
    public async Task RunReadOnlyAsync_CanExecuteGit()
    {
        var runner = new GitProcessRunner();

        var result = await runner.RunReadOnlyAsync(
            Directory.GetCurrentDirectory(),
            ["--version"],
            GitCommandTimeout
        );

        Assert.True(result.Succeeded);
        Assert.Equal(0, result.ExitCode);
    }

    [Fact]
    public async Task RunReadOnlyAsync_DisablesOptionalGitLocks()
    {
        var runner = new GitProcessRunner("dotnet");

        var helperPath = GetProcessTestHelperPath();

        Assert.True(File.Exists(helperPath), $"Process test helper not found: {helperPath}");

        var result = await runner.RunReadOnlyAsync(
            Directory.GetCurrentDirectory(),
            [helperPath, "print-env", "GIT_OPTIONAL_LOCKS"],
            GitCommandTimeout
        );

        Assert.True(result.Succeeded, result.StandardError);

        Assert.Equal("0", result.StandardOutput);
    }

    private static string GetProcessTestHelperPath()
    {
        var testOutputDirectory = new DirectoryInfo(AppContext.BaseDirectory);

        var targetFramework = testOutputDirectory.Name;

        var configurationDirectory = testOutputDirectory.Parent!;

        var hostDirectory = configurationDirectory.Parent!;

        var binDirectory = hostDirectory.Parent!;

        var testsProjectDirectory = binDirectory.Parent!;

        var testsDirectory = testsProjectDirectory.Parent!;

        return Path.Combine(
            testsDirectory.FullName,
            "Codelaxy.ProcessTestHelper",
            "bin",
            hostDirectory.Name,
            configurationDirectory.Name,
            targetFramework,
            "Codelaxy.ProcessTestHelper.dll"
        );
    }

    private static async Task<int> WaitForProcessIdAsync(
        string pidFile,
        CancellationToken cancellationToken
    )
    {
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (File.Exists(pidFile))
            {
                try
                {
                    var contents = await File.ReadAllTextAsync(pidFile, cancellationToken);

                    return int.Parse(contents);
                }
                catch (IOException)
                {
                    // The helper has published the PID file,
                    // but Windows may still briefly hold it.
                }
            }

            await Task.Delay(20, cancellationToken);
        }
    }

    private static string CreateTemporaryDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), $"Codelaxy Git Tests {Guid.NewGuid():N}");

        Directory.CreateDirectory(path);

        return path;
    }
}
