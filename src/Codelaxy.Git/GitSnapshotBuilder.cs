using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using Codelaxy.Contracts;

namespace Codelaxy.Git;

public sealed class GitSnapshotBuilder
{
    private const int SnapshotSchemaVersion = 1;

    private static readonly TimeSpan GitCommandTimeout = TimeSpan.FromMinutes(2);

    private readonly GitProcessRunner _runner;
    private readonly GitRepositoryDiscovery _discovery;

    public GitSnapshotBuilder(GitProcessRunner runner)
    {
        ArgumentNullException.ThrowIfNull(runner);

        _runner = runner;
        _discovery = new GitRepositoryDiscovery(runner);
    }

    public async Task<GitSnapshotBuildResult> BuildAsync(
        string startDirectory,
        CancellationToken cancellationToken = default
    )
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(startDirectory);

        var discoveryResult = await _discovery.DiscoverAsync(startDirectory, cancellationToken);

        if (!discoveryResult.Succeeded)
        {
            return Failure(discoveryResult.Diagnostic);
        }

        var repository = discoveryResult.Repository!;

        var headResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["rev-parse", "--verify", "HEAD"],
            cancellationToken
        );

        if (!headResult.Succeeded)
        {
            return Failure(CreateGitDiagnostic("Unable to read HEAD", headResult));
        }

        var indexResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["ls-files", "--stage", "-z"],
            cancellationToken
        );

        if (!indexResult.Succeeded)
        {
            return Failure(CreateGitDiagnostic("Unable to read Git index", indexResult));
        }

        IReadOnlyList<GitIndexEntry> indexEntries;

        try
        {
            indexEntries = GitIndexEntryParser.Parse(indexResult.StandardOutput);
        }
        catch (FormatException exception)
        {
            return Failure($"Unable to parse Git index: {exception.Message}");
        }

        var canonicalIndexParts = GitIndexEntryCanonicalizer.Canonicalize(indexEntries);

        var trackedResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["ls-files", "--cached", "--deduplicate", "-z"],
            cancellationToken
        );

        if (!trackedResult.Succeeded)
        {
            return Failure(CreateGitDiagnostic("Unable to enumerate tracked files", trackedResult));
        }

        var deletedResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["ls-files", "--deleted", "--deduplicate", "-z"],
            cancellationToken
        );

        if (!deletedResult.Succeeded)
        {
            return Failure(
                CreateGitDiagnostic("Unable to enumerate deleted tracked files", deletedResult)
            );
        }

        IReadOnlyDictionary<string, string> stagedBaseModes = new Dictionary<string, string>(
            StringComparer.Ordinal
        );

        if (OperatingSystem.IsWindows())
        {
            var stagedDiffResult = await RunRepositoryReadOnlyAsync(
                startDirectory,
                repository.TopLevel,
                [
                    "diff-index",
                    "--cached",
                    "--raw",
                    "-z",
                    "--no-abbrev",
                    "--no-renames",
                    "HEAD",
                    "--",
                ],
                cancellationToken
            );

            if (!stagedDiffResult.Succeeded)
            {
                return Failure(
                    CreateGitDiagnostic(
                        "Unable to read staged working-tree metadata",
                        stagedDiffResult
                    )
                );
            }

            try
            {
                stagedBaseModes = ParseStagedBaseModes(stagedDiffResult.StandardOutput);
            }
            catch (FormatException exception)
            {
                return Failure(
                    $"Unable to parse staged working-tree metadata: {exception.Message}"
                );
            }
        }

        var observedFileMode = OperatingSystem.IsWindows() ? "false" : "true";

        var worktreeDiffResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            [
                "-c",
                $"core.fileMode={observedFileMode}",
                "diff-files",
                "--raw",
                "-z",
                "--no-abbrev",
                "--no-renames",
            ],
            cancellationToken
        );

        if (!worktreeDiffResult.Succeeded)
        {
            return Failure(
                CreateGitDiagnostic(
                    "Unable to read tracked working-tree metadata",
                    worktreeDiffResult
                )
            );
        }

        IReadOnlyDictionary<string, string> workingTreeModes;

        try
        {
            workingTreeModes = ParseWorkingTreeModes(
                indexEntries,
                worktreeDiffResult.StandardOutput,
                stagedBaseModes
            );
        }
        catch (FormatException exception)
        {
            return Failure(
                $"Unable to parse tracked working-tree metadata: " + $"{exception.Message}"
            );
        }

        var trackedPaths = trackedResult.StandardOutput.Split(
            '\0',
            StringSplitOptions.RemoveEmptyEntries
        );

        var deletedPaths = deletedResult.StandardOutput.Split(
            '\0',
            StringSplitOptions.RemoveEmptyEntries
        );

        Array.Sort(trackedPaths, StringComparer.Ordinal);

        var deletedPathSet = new HashSet<string>(deletedPaths, StringComparer.Ordinal);

        var existingTrackedPaths = trackedPaths
            .Where(path => !deletedPathSet.Contains(path))
            .ToArray();

        var trackedObjectIds = Array.Empty<string>();

        if (existingTrackedPaths.Length > 0)
        {
            var hashArguments = new List<string> { "hash-object", "--no-filters", "--" };

            hashArguments.AddRange(existingTrackedPaths);

            var trackedHashResult = await RunRepositoryReadOnlyAsync(
                startDirectory,
                repository.TopLevel,
                hashArguments,
                cancellationToken
            );

            if (!trackedHashResult.Succeeded)
            {
                return Failure(
                    CreateGitDiagnostic(
                        "Unable to hash tracked working-tree files",
                        trackedHashResult
                    )
                );
            }

            trackedObjectIds = trackedHashResult.StandardOutput.Split(
                '\n',
                StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries
            );

            if (trackedObjectIds.Length != existingTrackedPaths.Length)
            {
                return Failure(
                    "Git returned an unexpected number " + "of tracked working-tree object hashes."
                );
            }
        }

        var trackedParts = new List<string>();

        var objectIndex = 0;

        foreach (var trackedPath in trackedPaths)
        {
            trackedParts.Add("path");
            trackedParts.Add(trackedPath);

            if (deletedPathSet.Contains(trackedPath))
            {
                trackedParts.Add("state");
                trackedParts.Add("missing");
                continue;
            }

            trackedParts.Add("state");
            trackedParts.Add("present");

            if (!workingTreeModes.TryGetValue(trackedPath, out var workingTreeMode))
            {
                return Failure(
                    $"Git did not provide a working-tree mode "
                        + $"for tracked path '{trackedPath}'."
                );
            }

            trackedParts.Add("mode");
            trackedParts.Add(workingTreeMode);

            trackedParts.Add("oid");
            trackedParts.Add(trackedObjectIds[objectIndex]);

            ++objectIndex;
        }

        var trackedFingerprint = CreateFingerprint(
            "codelaxy.snapshot.tracked-worktree.v2",
            trackedParts.ToArray()
        );

        var untrackedResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["ls-files", "--others", "--exclude-per-directory=.gitignore", "-z"],
            cancellationToken
        );

        if (!untrackedResult.Succeeded)
        {
            return Failure(
                CreateGitDiagnostic("Unable to enumerate untracked files", untrackedResult)
            );
        }

        var untrackedPaths = untrackedResult.StandardOutput.Split(
            '\0',
            StringSplitOptions.RemoveEmptyEntries
        );

        Array.Sort(untrackedPaths, StringComparer.Ordinal);

        var untrackedParts = new List<string>(untrackedPaths.Length * 2);

        if (untrackedPaths.Length > 0)
        {
            var hashArguments = new List<string> { "hash-object", "--no-filters", "--" };

            hashArguments.AddRange(untrackedPaths);

            var untrackedHashResult = await RunRepositoryReadOnlyAsync(
                startDirectory,
                repository.TopLevel,
                hashArguments,
                cancellationToken
            );

            if (!untrackedHashResult.Succeeded)
            {
                return Failure(
                    CreateGitDiagnostic("Unable to hash untracked files", untrackedHashResult)
                );
            }

            var untrackedObjectIds = untrackedHashResult.StandardOutput.Split(
                '\n',
                StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries
            );

            if (untrackedObjectIds.Length != untrackedPaths.Length)
            {
                return Failure(
                    "Git returned an unexpected number " + "of untracked object hashes."
                );
            }

            for (var index = 0; index < untrackedPaths.Length; ++index)
            {
                untrackedParts.Add(untrackedPaths[index]);

                untrackedParts.Add(untrackedObjectIds[index]);
            }
        }

        var untrackedFingerprint = CreateFingerprint(
            "codelaxy.snapshot.untracked.v1",
            untrackedParts.ToArray()
        );

        var headFingerprint = CreateFingerprint(
            "codelaxy.snapshot.head.v1",
            headResult.StandardOutput.Trim()
        );

        var indexFingerprint = CreateFingerprint(
            "codelaxy.snapshot.index.v2",
            canonicalIndexParts.ToArray()
        );

        var stagedFingerprint = CreateFingerprint(
            "codelaxy.snapshot.staged.v1",
            headFingerprint,
            indexFingerprint
        );

        var workingTreeFingerprint = CreateFingerprint(
            "codelaxy.snapshot.worktree.v1",
            trackedFingerprint,
            untrackedFingerprint
        );

        var snapshot = new Snapshot
        {
            SchemaVersion = SnapshotSchemaVersion,
            HeadFingerprint = headFingerprint,
            IndexFingerprint = indexFingerprint,
            WorkingTreeFingerprint = workingTreeFingerprint,
            StagedFingerprint = stagedFingerprint,
        };

        return new GitSnapshotBuildResult(snapshot, string.Empty);
    }

    private async Task<GitCommandResult> RunRepositoryReadOnlyAsync(
        string workingDirectory,
        string repositoryTopLevel,
        IEnumerable<string> commandArguments,
        CancellationToken cancellationToken
    )
    {
        var arguments = new List<string> { "-C", repositoryTopLevel };

        arguments.AddRange(commandArguments);

        return await _runner.RunReadOnlyAsync(
            workingDirectory,
            arguments,
            GitCommandTimeout,
            cancellationToken
        );
    }

    private static IReadOnlyDictionary<string, string> ParseWorkingTreeModes(
        IReadOnlyList<GitIndexEntry> indexEntries,
        string rawDiff,
        IReadOnlyDictionary<string, string> stagedBaseModes
    )
    {
        var modes = new Dictionary<string, string>(StringComparer.Ordinal);

        foreach (var entry in indexEntries)
        {
            if (entry.Stage != 0)
            {
                continue;
            }

            modes[entry.Path] = stagedBaseModes.TryGetValue(entry.Path, out var baseMode)
                ? baseMode
                : entry.Mode;
        }

        var records = rawDiff.Split('\0', StringSplitOptions.RemoveEmptyEntries);

        if (records.Length % 2 != 0)
        {
            throw new FormatException("Git raw diff output contains an incomplete record.");
        }

        for (var index = 0; index < records.Length; index += 2)
        {
            var metadata = records[index];
            var path = records[index + 1];

            if (!metadata.StartsWith(':'))
            {
                throw new FormatException("Git raw diff record has an unexpected format.");
            }

            var fields = metadata[1..].Split(' ', StringSplitOptions.RemoveEmptyEntries);

            if (fields.Length != 5)
            {
                throw new FormatException("Git raw diff metadata has an unexpected format.");
            }

            var oldMode = fields[0];
            var newMode = fields[1];

            if (newMode == "000000")
            {
                modes.Remove(path);
                continue;
            }

            if (oldMode != newMode)
            {
                modes[path] = newMode;
            }
        }

        return modes;
    }

    private static IReadOnlyDictionary<string, string> ParseStagedBaseModes(string rawDiff)
    {
        var modes = new Dictionary<string, string>(StringComparer.Ordinal);

        var records = rawDiff.Split('\0', StringSplitOptions.RemoveEmptyEntries);

        if (records.Length % 2 != 0)
        {
            throw new FormatException("Git raw diff output contains an incomplete record.");
        }

        for (var index = 0; index < records.Length; index += 2)
        {
            var metadata = records[index];
            var path = records[index + 1];

            if (!metadata.StartsWith(':'))
            {
                throw new FormatException("Git raw diff record has an unexpected format.");
            }

            var fields = metadata[1..].Split(' ', StringSplitOptions.RemoveEmptyEntries);

            if (fields.Length != 5)
            {
                throw new FormatException("Git raw diff metadata has an unexpected format.");
            }

            var oldMode = fields[0];
            var newMode = fields[1];

            if (oldMode != newMode && IsRegularFileMode(oldMode) && IsRegularFileMode(newMode))
            {
                modes[path] = oldMode;
            }
        }

        return modes;
    }

    private static bool IsRegularFileMode(string mode)
    {
        return mode is "100644" or "100755";
    }

    private static GitSnapshotBuildResult Failure(string diagnostic)
    {
        if (string.IsNullOrWhiteSpace(diagnostic))
        {
            diagnostic = "Git repository state could not be observed.";
        }

        return new GitSnapshotBuildResult(null, diagnostic);
    }

    private static string CreateGitDiagnostic(string prefix, GitCommandResult result)
    {
        var detail = result.StandardError.Trim();

        return string.IsNullOrWhiteSpace(detail) ? prefix : $"{prefix}: {detail}";
    }

    private static string CreateFingerprint(string domain, params string[] parts)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);

        AppendHashPart(hash, domain);

        foreach (var part in parts)
        {
            AppendHashPart(hash, part);
        }

        var digest = hash.GetHashAndReset();

        return $"sha256:{Convert.ToHexString(digest).ToLowerInvariant()}";
    }

    private static void AppendHashPart(IncrementalHash hash, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);

        Span<byte> length = stackalloc byte[sizeof(int)];

        BinaryPrimitives.WriteInt32BigEndian(length, bytes.Length);

        hash.AppendData(length);
        hash.AppendData(bytes);
    }
}
