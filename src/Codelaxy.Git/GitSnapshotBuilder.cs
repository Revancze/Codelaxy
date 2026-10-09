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
        var firstResult = await BuildSingleObservationAsync(startDirectory, cancellationToken);

        if (!firstResult.Succeeded)
        {
            return firstResult;
        }

        var secondResult = await BuildSingleObservationAsync(startDirectory, cancellationToken);

        if (!secondResult.Succeeded)
        {
            return secondResult;
        }

        var firstSnapshot = firstResult.Snapshot!;
        var secondSnapshot = secondResult.Snapshot!;

        if (
            firstSnapshot.SchemaVersion != secondSnapshot.SchemaVersion
            || !string.Equals(
                firstSnapshot.HeadFingerprint,
                secondSnapshot.HeadFingerprint,
                StringComparison.Ordinal
            )
            || !string.Equals(
                firstSnapshot.IndexFingerprint,
                secondSnapshot.IndexFingerprint,
                StringComparison.Ordinal
            )
            || !string.Equals(
                firstSnapshot.WorkingTreeFingerprint,
                secondSnapshot.WorkingTreeFingerprint,
                StringComparison.Ordinal
            )
            || !string.Equals(
                firstSnapshot.StagedFingerprint,
                secondSnapshot.StagedFingerprint,
                StringComparison.Ordinal
            )
        )
        {
            return Failure("Repository changed during snapshot capture.");
        }

        return secondResult;
    }

    private async Task<GitSnapshotBuildResult> BuildSingleObservationAsync(
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

        var fileSystemTopLevelResult = await _runner.RunReadOnlyAsync(
            startDirectory,
            ["rev-parse", "--show-cdup"],
            GitCommandTimeout,
            cancellationToken
        );

        if (!fileSystemTopLevelResult.Succeeded)
        {
            return Failure(
                CreateGitDiagnostic(
                    "Unable to resolve host-native repository root",
                    fileSystemTopLevelResult
                )
            );
        }

        var fileSystemTopLevel = ResolveFileSystemTopLevel(
            startDirectory,
            fileSystemTopLevelResult.StandardOutput
        );

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
            ["ls-files", "--stage", "-t", "-z"],
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

        var coreSymlinksResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["config", "--type=bool", "--default=true", "--get", "core.symlinks"],
            cancellationToken
        );

        if (!coreSymlinksResult.Succeeded)
        {
            return Failure(CreateGitDiagnostic("Unable to read core.symlinks", coreSymlinksResult));
        }

        if (!bool.TryParse(coreSymlinksResult.StandardOutput.Trim(), out var coreSymlinksEnabled))
        {
            return Failure(
                $"Git returned an invalid core.symlinks value: "
                    + $"'{coreSymlinksResult.StandardOutput.Trim()}'."
            );
        }

        var trackedPaths = indexEntries
            .Select(entry => entry.Path)
            .Distinct(StringComparer.Ordinal)
            .OrderBy(path => path, StringComparer.Ordinal)
            .ToArray();

        var indexEntriesByPath = indexEntries
            .GroupBy(entry => entry.Path, StringComparer.Ordinal)
            .ToDictionary(
                group => group.Key,
                group => (IReadOnlyList<GitIndexEntry>)group.ToArray(),
                StringComparer.Ordinal
            );

        var observer = new WorkingTreeEntryObserver(fileSystemTopLevel);

        var trackedStates = new Dictionary<string, string>(StringComparer.Ordinal);
        var trackedKinds = new Dictionary<string, string>(StringComparer.Ordinal);
        var trackedModes = new Dictionary<string, string>(StringComparer.Ordinal);
        var trackedObjectIds = new Dictionary<string, string>(StringComparer.Ordinal);

        var regularTrackedPaths = new List<string>();
        var symbolicLinkPaths = new List<string>();

        foreach (var trackedPath in trackedPaths)
        {
            var pathIndexEntries = indexEntriesByPath[trackedPath];

            if (pathIndexEntries.Any(entry => entry.Mode == "160000"))
            {
                return Failure(
                    $"Tracked gitlink '{trackedPath}' is not yet supported "
                        + "for exact working-tree observation."
                );
            }

            var observationResult = observer.Observe(trackedPath);

            if (!observationResult.Succeeded)
            {
                return Failure(observationResult.Diagnostic);
            }

            var observation = observationResult.Observation!;

            var skipWorktree = pathIndexEntries.Any(entry => entry.SkipWorktree);

            if (observation.Kind == WorkingTreeEntryKind.Missing)
            {
                trackedStates[trackedPath] = skipWorktree ? "unmaterialized" : "missing";

                continue;
            }

            if (observation.Kind == WorkingTreeEntryKind.ReparsePoint)
            {
                return Failure(
                    $"Tracked reparse point '{trackedPath}' is not yet supported "
                        + "for exact working-tree observation."
                );
            }

            if (observation.Kind == WorkingTreeEntryKind.Directory)
            {
                trackedStates[trackedPath] = "type-conflict";
                trackedKinds[trackedPath] = "directory";

                continue;
            }

            trackedStates[trackedPath] = "present";

            var stageZeroEntry = pathIndexEntries.SingleOrDefault(entry => entry.Stage == 0);

            if (observation.Kind == WorkingTreeEntryKind.SymbolicLink)
            {
                trackedKinds[trackedPath] = "symlink";
                trackedModes[trackedPath] = "120000";
                symbolicLinkPaths.Add(trackedPath);

                continue;
            }

            var materializedSymbolicLink = stageZeroEntry?.Mode == "120000" && !coreSymlinksEnabled;

            if (materializedSymbolicLink)
            {
                trackedKinds[trackedPath] = "symlink";
                trackedModes[trackedPath] = "120000";
            }
            else
            {
                trackedKinds[trackedPath] = "regular";

                var workingTreeMode =
                    observation.Mode
                    ?? GetWindowsWorkingTreeRegularFileMode(
                        trackedPath,
                        pathIndexEntries,
                        stagedBaseModes
                    );

                if (workingTreeMode is null)
                {
                    return Failure(
                        $"Unable to determine working-tree mode "
                            + $"for tracked path '{trackedPath}'."
                    );
                }

                trackedModes[trackedPath] = workingTreeMode;
            }

            regularTrackedPaths.Add(trackedPath);
        }

        if (regularTrackedPaths.Count > 0)
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

            if (regularObjectIds.Length != regularTrackedPaths.Count)
            {
                return Failure(
                    "Git returned an unexpected number " + "of tracked working-tree object hashes."
                );
            }

            for (var index = 0; index < regularTrackedPaths.Count; ++index)
            {
                trackedObjectIds[regularTrackedPaths[index]] = regularObjectIds[index];
            }
        }

        foreach (var symbolicLinkPath in symbolicLinkPaths)
        {
            var fullPath = Path.Combine(fileSystemTopLevel, symbolicLinkPath);

            var linkTarget = new FileInfo(fullPath).LinkTarget;

            if (linkTarget is null)
            {
                return Failure($"Unable to read tracked symbolic link " + $"'{symbolicLinkPath}'.");
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
                        $"Unable to hash tracked symbolic link " + $"'{symbolicLinkPath}'",
                        symlinkHashResult
                    )
                );
            }

            trackedObjectIds[symbolicLinkPath] = symlinkHashResult.StandardOutput.Trim();
        }

        var trackedParts = new List<string>();

        foreach (var trackedPath in trackedPaths)
        {
            trackedParts.Add("path");
            trackedParts.Add(trackedPath);

            var state = trackedStates[trackedPath];

            trackedParts.Add("state");
            trackedParts.Add(state);

            if (state == "missing" || state == "unmaterialized")
            {
                continue;
            }

            if (!trackedKinds.TryGetValue(trackedPath, out var kind))
            {
                return Failure(
                    $"Unable to determine working-tree kind " + $"for tracked path '{trackedPath}'."
                );
            }

            trackedParts.Add("kind");
            trackedParts.Add(kind);

            if (state == "type-conflict")
            {
                continue;
            }

            if (!trackedModes.TryGetValue(trackedPath, out var mode))
            {
                return Failure(
                    $"Unable to determine working-tree mode " + $"for tracked path '{trackedPath}'."
                );
            }

            trackedParts.Add("mode");
            trackedParts.Add(mode);

            if (!trackedObjectIds.TryGetValue(trackedPath, out var objectId))
            {
                return Failure(
                    $"Git did not provide a working-tree object hash "
                        + $"for tracked path '{trackedPath}'."
                );
            }

            trackedParts.Add("oid");
            trackedParts.Add(objectId);
        }

        var trackedFingerprint = CreateFingerprint(
            "codelaxy.snapshot.tracked-worktree.v3",
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

        var untrackedParts = new List<string>(untrackedPaths.Length * 8);

        if (untrackedPaths.Length > 0)
        {
            var regularUntrackedPaths = new List<string>();
            var untrackedModes = new Dictionary<string, string>(StringComparer.Ordinal);
            var untrackedObjectIds = new Dictionary<string, string>(StringComparer.Ordinal);
            var untrackedKinds = new Dictionary<string, string>(StringComparer.Ordinal);

            foreach (var untrackedPath in untrackedPaths)
            {
                var fullPath = Path.Combine(fileSystemTopLevel, untrackedPath);
                var linkTarget = new FileInfo(fullPath).LinkTarget;

                if (linkTarget is null)
                {
                    regularUntrackedPaths.Add(untrackedPath);
                    untrackedKinds[untrackedPath] = "regular";
                    untrackedModes[untrackedPath] = GetUntrackedRegularFileMode(fullPath);

                    continue;
                }

                untrackedKinds[untrackedPath] = "symlink";
                untrackedModes[untrackedPath] = "120000";

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

                if (!untrackedModes.TryGetValue(untrackedPath, out var untrackedMode))
                {
                    return Failure(
                        $"Unable to determine untracked entry mode for path '{untrackedPath}'."
                    );
                }

                untrackedParts.Add("path");
                untrackedParts.Add(untrackedPath);

                untrackedParts.Add("kind");
                untrackedParts.Add(untrackedKind);

                untrackedParts.Add("mode");
                untrackedParts.Add(untrackedMode);

                untrackedParts.Add("oid");
                untrackedParts.Add(objectId);
            }
        }

        var finalHeadResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["rev-parse", "--verify", "HEAD"],
            cancellationToken
        );

        if (!finalHeadResult.Succeeded)
        {
            return Failure(
                CreateGitDiagnostic(
                    "Unable to re-read HEAD after snapshot capture",
                    finalHeadResult
                )
            );
        }

        var finalIndexResult = await RunRepositoryReadOnlyAsync(
            startDirectory,
            repository.TopLevel,
            ["ls-files", "--stage", "-t", "-z"],
            cancellationToken
        );

        if (!finalIndexResult.Succeeded)
        {
            return Failure(
                CreateGitDiagnostic(
                    "Unable to re-read Git index after snapshot capture",
                    finalIndexResult
                )
            );
        }

        if (
            !string.Equals(
                headResult.StandardOutput,
                finalHeadResult.StandardOutput,
                StringComparison.Ordinal
            )
            || !string.Equals(
                indexResult.StandardOutput,
                finalIndexResult.StandardOutput,
                StringComparison.Ordinal
            )
        )
        {
            return Failure("Repository changed during snapshot capture.");
        }

        var untrackedFingerprint = CreateFingerprint(
            "codelaxy.snapshot.untracked.v3",
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

    private static string? GetWindowsWorkingTreeRegularFileMode(
        string path,
        IReadOnlyList<GitIndexEntry> indexEntries,
        IReadOnlyDictionary<string, string> stagedBaseModes
    )
    {
        if (
            stagedBaseModes.TryGetValue(path, out var stagedBaseMode)
            && IsRegularFileMode(stagedBaseMode)
        )
        {
            return stagedBaseMode;
        }

        var regularModes = indexEntries
            .Select(entry => entry.Mode)
            .Where(IsRegularFileMode)
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        return regularModes.Length == 1 ? regularModes[0] : null;
    }

    private static string ResolveFileSystemTopLevel(string startDirectory, string rawCdup)
    {
        var relativeTopLevel = GitRepositoryDiscovery.RemoveGitLineTerminator(rawCdup);

        return Path.GetFullPath(Path.Combine(Path.GetFullPath(startDirectory), relativeTopLevel));
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

    private static string GetUntrackedRegularFileMode(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            return "100644";
        }

        var mode = File.GetUnixFileMode(path);

        return (mode & UnixFileMode.UserExecute) != 0 ? "100755" : "100644";
    }
}
