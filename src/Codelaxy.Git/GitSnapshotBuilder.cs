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

        var trackedObjectIds = new Dictionary<string, string>(StringComparer.Ordinal);

        foreach (var trackedPath in existingTrackedPaths)
        {
            if (!workingTreeModes.ContainsKey(trackedPath))
            {
                return Failure(
                    $"Git did not provide a working-tree mode "
                        + $"for tracked path '{trackedPath}'."
                );
            }
        }

        var regularTrackedPaths = existingTrackedPaths
            .Where(path => workingTreeModes[path] != "120000")
            .ToArray();

        if (regularTrackedPaths.Length > 0)
        {
            var hashArguments = new List<string> { "hash-object", "--no-filters", "--" };

            hashArguments.AddRange(regularTrackedPaths);

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

            var regularObjectIds = trackedHashResult.StandardOutput.Split(
                '\n',
                StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries
            );

            if (regularObjectIds.Length != regularTrackedPaths.Length)
            {
                return Failure(
                    "Git returned an unexpected number " + "of tracked working-tree object hashes."
                );
            }

            for (var index = 0; index < regularTrackedPaths.Length; ++index)
            {
                trackedObjectIds[regularTrackedPaths[index]] = regularObjectIds[index];
            }
        }

        var symlinkPaths = existingTrackedPaths
            .Where(path => workingTreeModes[path] == "120000")
            .ToArray();

        foreach (var symlinkPath in symlinkPaths)
        {
            var fullPath = Path.Combine(repository.TopLevel, symlinkPath);

            var linkTarget = new FileInfo(fullPath).LinkTarget;

            if (linkTarget is null)
            {
                var materializedHashResult = await RunRepositoryReadOnlyAsync(
                    startDirectory,
                    repository.TopLevel,
                    ["hash-object", "--no-filters", "--", symlinkPath],
                    cancellationToken
                );

                if (!materializedHashResult.Succeeded)
                {
                    return Failure(
                        CreateGitDiagnostic(
                            $"Unable to hash materialized symbolic link '{symlinkPath}'",
                            materializedHashResult
                        )
                    );
                }

                trackedObjectIds[symlinkPath] = materializedHashResult.StandardOutput.Trim();

                continue;
            }

            var symlinkHashResult = await RunRepositoryReadOnlyAsync(
                startDirectory,
                repository.TopLevel,
                ["hash-object", "--stdin"],
                Encoding.UTF8.GetBytes(linkTarget),
                cancellationToken
            );

            if (!symlinkHashResult.Succeeded)
            {
                return Failure(
                    CreateGitDiagnostic(
                        $"Unable to hash tracked symbolic link '{symlinkPath}'",
                        symlinkHashResult
                    )
                );
            }

            trackedObjectIds[symlinkPath] = symlinkHashResult.StandardOutput.Trim();
        }

        var trackedParts = new List<string>();

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

            if (!trackedObjectIds.TryGetValue(trackedPath, out var trackedObjectId))
            {
                return Failure(
                    $"Git did not provide a working-tree object hash "
                        + $"for tracked path '{trackedPath}'."
                );
            }

            trackedParts.Add("oid");
            trackedParts.Add(trackedObjectId);
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

        var untrackedParts = new List<string>(untrackedPaths.Length * 6);

        if (untrackedPaths.Length > 0)
        {
            var regularUntrackedPaths = new List<string>();
            var untrackedObjectIds = new Dictionary<string, string>(StringComparer.Ordinal);
            var untrackedKinds = new Dictionary<string, string>(StringComparer.Ordinal);

            foreach (var untrackedPath in untrackedPaths)
            {
                var fullPath = Path.Combine(repository.TopLevel, untrackedPath);
                var linkTarget = new FileInfo(fullPath).LinkTarget;

                if (linkTarget is null)
                {
                    regularUntrackedPaths.Add(untrackedPath);
                    untrackedKinds[untrackedPath] = "regular";

                    continue;
                }

                untrackedKinds[untrackedPath] = "symlink";

                var symlinkHashResult = await RunRepositoryReadOnlyAsync(
                    startDirectory,
                    repository.TopLevel,
                    ["hash-object", "--stdin"],
                    Encoding.UTF8.GetBytes(linkTarget),
                    cancellationToken
                );

                if (!symlinkHashResult.Succeeded)
                {
                    return Failure(
                        CreateGitDiagnostic(
                            $"Unable to hash untracked symbolic link '{untrackedPath}'",
                            symlinkHashResult
                        )
                    );
                }

                untrackedObjectIds[untrackedPath] = symlinkHashResult.StandardOutput.Trim();
            }

            if (regularUntrackedPaths.Count > 0)
            {
                var hashArguments = new List<string> { "hash-object", "--no-filters", "--" };

                hashArguments.AddRange(regularUntrackedPaths);

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

                var regularObjectIds = untrackedHashResult.StandardOutput.Split(
                    '\n',
                    StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries
                );

                if (regularObjectIds.Length != regularUntrackedPaths.Count)
                {
                    return Failure("Git returned an unexpected number of untracked object hashes.");
                }

                for (var index = 0; index < regularUntrackedPaths.Count; ++index)
                {
                    untrackedObjectIds[regularUntrackedPaths[index]] = regularObjectIds[index];
                }
            }

            foreach (var untrackedPath in untrackedPaths)
            {
                if (!untrackedKinds.TryGetValue(untrackedPath, out var untrackedKind))
                {
                    return Failure(
                        $"Unable to determine untracked entry kind for path '{untrackedPath}'."
                    );
                }

                if (!untrackedObjectIds.TryGetValue(untrackedPath, out var objectId))
                {
                    return Failure(
                        $"Git did not provide a working-tree object hash "
                            + $"for untracked path '{untrackedPath}'."
                    );
                }

                untrackedParts.Add("path");
                untrackedParts.Add(untrackedPath);

                untrackedParts.Add("kind");
                untrackedParts.Add(untrackedKind);

                untrackedParts.Add("oid");
                untrackedParts.Add(objectId);
            }
        }

        var untrackedFingerprint = CreateFingerprint(
            "codelaxy.snapshot.untracked.v2",
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

    private async Task<GitCommandResult> RunRepositoryReadOnlyAsync(
        string workingDirectory,
        string repositoryTopLevel,
        IEnumerable<string> commandArguments,
        byte[] standardInput,
        CancellationToken cancellationToken
    )
    {
        var arguments = new List<string> { "-C", repositoryTopLevel };

        arguments.AddRange(commandArguments);

        return await _runner.RunReadOnlyAsync(
            workingDirectory,
            arguments,
            GitCommandTimeout,
            standardInput,
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
