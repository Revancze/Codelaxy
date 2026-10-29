# Snapshot test matrix

Status of `GitSnapshotBuilder` against the Git object model and the repository
states Codelaxy must judge. A cell is DONE only when a test proves it.

Legend:

| Mark | Meaning |
|---|---|
| ✅ | covered by a test (name given) |
| ❌ | known defect, reproduced |
| ❓ | untested, behaviour unknown |
| 📝 | needs an explicit decision before a test can be written |
| ➖ | not applicable |

Fingerprints: **H** = Head, **I** = Index, **S** = Staged, **W** = WorkingTree.
`=` must stay equal, `≠` must change.

---

## 1. Entry kinds

Every mode Git can store, and every kind of object that can appear untracked.

| Entry | Tracked | Untracked | Notes |
|---|---|---|---|
| regular file `100644` | ✅ ChangesWorkingTreeFingerprintWhenContentChanges | ✅ ChangesWorkingTreeFingerprintWhenUntrackedContentChanges | |
| executable file `100755` | ✅ covered by 5 executable/fileMode tests | ✅ Linux: BuildAsync_ChangesWorkingTreeIdentityWhenUntrackedExecutableBitChangesOnLinux | Linux: the observer reads the executable bit of an untracked file, and the bit counts in W. Windows: the observer does not read an executable bit and records untracked regular files as `100644`. |
| empty file | ✅ DistinguishesDeletedAndEmptyTrackedFile | ❓ | |
| symlink to file `120000` | ✅ tracked symlink tests | ✅ untracked symlink tests | hashes link target text |
| symlink retargeted, same content | ✅ W changes | ✅ W changes | |
| dangling symlink | ✅ supported | ✅ supported | legal Git state |
| symlink to directory | ✅ supported | ✅ supported | |
| symlink pointing outside repo | ✅ independent of external target content | ✅ same | |
| gitlink / submodule `160000` | 📝 reported failure (`hash-object` on directory); support decision pending | ➖ | observed on Windows; regression test and scope decision pending |
| nested repository | ➖ | 📝 reported failure (`dir/` passed to `hash-object`); support decision pending | observed under `.claude/worktrees/`; reproduce independently |
| linked worktree inside worktree | ➖ | 📝 suspected nested-repository failure mode; decision pending | requires independent test |
| empty directory | ➖ | ❓ | Git ignores it; W should not change 📝 |
| sparse index directory `040000` | ❓ | ➖ | only with sparse index |

## 2. State transitions

What each change must and must not do to the four fingerprints.

| Change | H | I | S | W | Status |
|---|---|---|---|---|---|
| no change, second run | = | = | = | = | ✅ ProducesSameFingerprintsForSameRepositoryState |
| edit tracked file, unstaged | = | = | = | ≠ | ✅ ChangesWorkingTreeFingerprintWhenContentChanges |
| stage an edit | = | ≠ | ≠ | = | ✅ ChangesIndexAndStagedFingerprintsWhenStagedContentChanges |
| unstaged edit leaves staged identity intact | = | = | = | ≠ | ✅ SeparatesStagedAndWorkingTreeIdentity |
| add / edit untracked file | = | = | = | ≠ | ✅ ChangesWorkingTreeFingerprintWhenUntrackedContentChanges |
| delete tracked file, unstaged | = | = | = | ≠ | ✅ ChangesOnlyWorkingTreeFingerprintForUnstagedDeletion |
| delete tracked file, staged | = | ≠ | ≠ | ≠ | ✅ ChangesIndexAndStagedFingerprintsForStagedDeletion |
| staged rename | = | ≠ | ≠ | ≠ | ✅ ChangesIndexAndStagedFingerprintsForStagedRename |
| staged copy | = | ≠ | ≠ | ≠ | ✅ RepresentsStagedCopyByHardState |
| merge conflict (stages 1/2/3) | = | ≠ | ≠ | ≠ | ✅ SupportsUnmergedRepositoryState |
| new commit with identical tree, unchanged canonical index and materialized state | ≠ | = | ≠ | = | ❓ semantic expectation; runtime test pending |
| switch branch name, same HEAD, index and materialized state | = | = | = | = | ❓ branch/ref name must not affect identity; runtime test pending |
| checkout different repository state | depends | depends | depends | depends | 📝 define exact fixture before asserting fingerprint transitions |
| touch file (mtime only) | = | = | = | = | ❓ runtime test missing; only static timestamp invariant exists |
| index stat refresh (`git status` without optional-locks guard) | = | = | = | = | ❓ |
| edit ignored file | = | = | = | = | ❓ |
| file ignored only by `.git/info/exclude` | = | = | = | ≠ | 📝 policy: intentionally counted in W; observer-local excludes must not change snapshot identity |
| symlink retargeted, same content | = | = | = | ≠ | ✅ tracked + untracked retarget tests on Linux |
| CRLF ↔ LF on disk, same blob | = | = | = | 📝 | byte-exact or Git-semantic? |
| Windows chmod | ➖ | ➖ | ➖ | ➖ | NTFS has no executable bit |

## 3. Configuration and environment independence

Snapshot identity must not depend on how the observer is configured.

| Input | Status |
|---|---|
| `status.renames` | ✅ FingerprintsDoNotDependOnStatusRenameConfiguration |
| `core.autocrlf` | ✅ FingerprintsDoNotDependOnCoreAutoCrlfConfiguration |
| repository-declared clean filter (`filter.<name>.clean`) with `core.autocrlf=true` | ✅ untracked files, Windows + Linux: BuildAsync_DoesNotRunCleanFilterOrConvertUntrackedFileWithAutoCrlf. The test first proves, with the same fixture, that where filters are allowed the filter runs and the blob is converted (LF, pinned blob ID); then that `--no-filters` hashes the bytes on disk (pinned CRLF blob ID); then that BuildAsync runs no filter (marker file absent) and produces the same W as a control repository without the filter and with `core.autocrlf=false`. It fails, with an F12 message, when the untracked batch loses `--no-filters` (checked on Windows and Linux, audit run 2026-10-28). Tracked files: dropping `--no-filters` from the tracked batch is killed on Windows by FingerprintsDoNotDependOnCoreAutoCrlfConfiguration (not run on Linux); a clean filter on a tracked file has no dedicated test ❓ |
| `core.excludesFile` | ✅ FingerprintsDoNotDependOnCoreExcludesFile |
| `core.fileMode` | ✅ FileModeConfigurationDoesNotChangeExecutableWorkingTreeIdentityOnLinux |
| `core.symlinks` | ✅ SupportsTrackedSymlinkMaterializedAsRegularFileWhenCoreSymlinksFalse + UsesSameWorkingTreeFingerprintForMaterializedAndNativeTrackedSymlinkOnLinux |
| `core.ignoreCase` | ❓ identity independence untested; with `true`, a case-only rename never yields a Snapshot blind to it (see §5) |
| inherited `GIT_*` repository-local variables | ✅ Invariants/GitEnvironmentInvariantTests + drift test |
| console code page (e.g. 852) | ✅ CreateProcessStartInfo_PinsRedirectedGitOutputToUtf8 |
| `core.untrackedCache` | ❓ independent probe pending |

## 4. Repository kinds

| Repository | Status | Notes |
|---|---|---|
| SHA-1 | ✅ (all tests) | |
| SHA-256 | ✅ SupportsSha256Repository | |
| unborn HEAD (no commit yet) | 📝 reported rejection by `rev-parse --verify HEAD` | decide whether to represent unborn HEAD or fail conservatively |
| detached HEAD | ❓ | covered in discovery, not in snapshot |
| linked worktree as the observed repo | ❓ | |
| shallow clone | ❓ | H is commit oid; likely fine |
| sparse checkout | ❓ | skip-worktree entries missing on disk |
| bare repository | ✅ Invariants/SnapshotBuild_ReturnsNoSnapshotForBareRepository | diagnostic, no snapshot |
| outside any repository | ✅ Invariants/SnapshotBuild_ReturnsNoSnapshotOutsideRepository | |

## 5. Paths and scale

| Case | Status | Notes |
|---|---|---|
| path with spaces | ✅ tracked and untracked, Windows + Linux: BuildAsync_ObservesSpecialNamesWithoutLosingWorkingTreeChanges (`space name.txt`) | Detection of change only: the test edits each special-named file in turn and asserts that H, I and S stay equal and W changes. It pins no Golden value and does not check which object ID belongs to which path; that attribution is covered by the F11 Golden tests (§7), which use ASCII names. On Linux the same test also covers names with a leading quote, a backslash and a tab. A runner test for spaces exists as well. |
| Unicode paths in index (NFC/NFD and supplementary-plane characters) | ✅ IndexGoldenUnicode001_GitFixturePreservesPathsAndProducesExpectedIndexFingerprint | A real Git fixture with NFC and NFD `é` and supplementary-plane names pins the index fingerprint. Unicode paths in W: ✅ detection only, tracked and untracked, Windows + Linux: BuildAsync_ObservesSpecialNamesWithoutLosingWorkingTreeChanges with `český-žluťoučký.txt`, `日本語-文書.txt`, `emoji-😀.txt` (U+1F600, supplementary plane), precomposed `composed-é.txt` and decomposed `decomposed-e` + U+0301; no W value is pinned. |
| path with leading `-` | ✅ tracked and untracked, Windows + Linux: BuildAsync_ObservesSpecialNamesWithoutLosingWorkingTreeChanges (`-leading-dash.txt`) | Regular files are named in quoted records on standard input, not as command-line arguments, so a leading `-` cannot be taken for an option. The test proves success and that W follows the file; the same evidence boundary as for spaces applies (change detection, no Golden value). |
| many files (long path list) | ✅ Windows, regression proven. Linux: tests run and pass, no RED claimed | Regular tracked paths and, separately, regular untracked paths are sent to `git hash-object --no-filters --stdin-paths` on standard input (`GitObjectHasher`: strict UTF-8, C-style quoting, validated output) instead of the command line; symbolic-link targets are hashed separately with `--stdin`. Tests: Windows only BuildAsync_HandlesTrackedPathsExceedingWindowsCommandLineLimit and BuildAsync_HandlesUntrackedPathsExceedingWindowsCommandLineLimit (450 paths, about 38 000 and 40 000 characters, above the 32 767-character command-line limit); Windows + Linux BuildAsync_ReadableFilesAmongManyPaths_Succeeds, BuildAsync_UnreadableFileAmongManyPaths_ReturnsFailureWithoutThrowing (Git stops reading standard input early; the payload is asserted to be at least 128 KiB) and GitObjectHasherTests. Regression evidence: the same tests against the previous builder (`ab71863`) fail on Windows (6 tests; audit run 2026-10-28, not a CI run). Boundary: the previous implementation was not run on Linux and is not expected to fail there at these sizes (about 130 KiB of paths against an `ARG_MAX` of 2 MiB), so no Linux RED is claimed. The Linux limit (an earlier audit checkpoint reported 20 000 files passing and 100 000 failing) was not re-measured. |
| path containing LF (newline) | ✅ Linux, tracked and untracked: BuildAsync_AcceptsLineFeedPathOnLinux. ➖ Windows | NTFS cannot hold LF in a file name, so there is no Windows snapshot test. The batch input writes every byte outside 33–126, and `"` and `\`, as a three-digit octal escape inside quotes, so an LF cannot split a record: GitObjectHasherTests.TryEncodePaths_EncodesLineFeedWithGitOctalEscape (all platforms). The Linux test asserts success and that W changes; it does not pin a Golden value for the LF path. |
| file changes during snapshot | ✅ Linux regression tests | BuildAsync performs two complete observations and compares SchemaVersion, H/I/S/W fingerprints. Detected drift returns a diagnostic without a Snapshot. Coordinated ABA remains a known observation-model limitation. Windows-specific concurrency regression is not yet proven. |
| filename differing only in case | ✅ with `core.ignoreCase=true`, never a Snapshot blind to the rename: BuildAsync_DoesNotLoseCaseOnlyRenamedTrackedFileWhenGitIgnoresCase (all platforms) + BuildAsync_DoesNotLoseCaseOnlyRenamedTrackedFileOnWindows | The tests accept either a refusal ("Case-only path mismatch") or a correctly distinct W. The current implementation refuses. `core.ignoreCase=false` ❓ |
| symlink target with invalid UTF-8 bytes (Unix) | untracked ✅ never merged: BuildAsync_DoesNotMergeSymlinkTargetsWithDifferentInvalidUtf8OnLinux; tracked ❓ untested | The test accepts either a refusal or a distinct W. The current implementation refuses a lossily decoded target. Tracked symlinks pass through the same check in code, but no test proves it. Arbitrary target-byte fidelity stays unsupported. |

## 6. Platforms

Platform coverage is evaluated against the supported
behavior of each scenario, not by requiring every test
to pass on every operating system.

Tests named `…OnLinux` exercise their target behavior
only on Linux. An early return on Windows does not
constitute Windows coverage, even if the test runner
reports success.

Every scenario must have an explicit disposition:

- SUPPORTED
- CONSERVATIVE FAILURE
- OUT OF SCOPE
- KNOWN LIMITATION

A scenario is complete only when its required behavior
is supported by applicable evidence or an explicitly
documented scope decision.

---

## 7. Independent Golden reference tests

Golden tests compare snapshot fingerprints against fixed values
calculated independently of Codelaxy.

| Fingerprint | Golden coverage | Evidence |
|---|---|---|
| H — HEAD | ✅ Windows + Ubuntu | HsGolden001_ProducesIndependentExpectedFingerprints |
| I — Index | ✅ | INDEX-GOLDEN-001 and INDEX-GOLDEN-UNICODE-001 |
| S — Staged | ✅ Windows + Ubuntu | HsGolden001_ProducesIndependentExpectedFingerprints |
| W — WorkingTree | ✅ Windows + Ubuntu | WORKTREE-GOLDEN-001; WorktreeGolden001_ProducesIndependentExpectedFingerprints |
| W — object ID ↔ path attribution (F11) | ✅ Windows + Ubuntu (symlink case Linux only) | WorktreeGoldenF11_MultiplePathsKeepOidAttribution (tracked and untracked), WorktreeGoldenF11_MixedTrackedStatesKeepOidAttribution (missing file, directory conflict), WorktreeGoldenF11_MixedUntrackedSymlinkKeepsOidAttribution (Linux only) |

H/S Golden fixture:
- fixed SHA-1 HEAD commit;
- empty index and one staged regular file;
- independently calculated SHA-256 reference values;
- H stays equal while I and S change.

W Golden fixture:
- fixed SHA-1 HEAD commit;
- staged regular file and untracked regular file;
- H, I and S remain unchanged;
- unstaged content edit produces two independently pinned W values;
- reference calculated by tests/golden_worktree_reference.py.

F11 Golden fixtures (the batch hash keeps every object ID attached to its path):
- three files whose blob-ID order differs from their path order (a.txt `alpha`, b.txt `charlie`, c.txt `bravo`), once tracked and once untracked;
- tracked states: b.txt missing, or replaced by a directory (no object ID in W);
- Linux only: an untracked symlink between two regular files, retargeted to a.txt and to c.txt;
- reference values: tests/golden_f11_reference.py (hashlib only, no Codelaxy code). It also cross-checks the constants pinned in the C# tests and, on Unix, the real-Git symlink fixture (not verified on Windows);
- mutants (audit run 2026-10-28): sorting the batch object IDs before pairing them with the paths is killed on the tracked batch and on the untracked batch, each by the corresponding MultiplePaths case. The reference's M8/M9 variants exist only as a Python model and were not executed against the C# code;
- CI: run 40724167266 (PR head d020ecb, test merge 40d59be), Windows and Ubuntu SUCCESS; the symlink test is skipped on Windows.

Cross-platform evidence:
- GitHub Actions run 39478019502;
- windows-latest: SUCCESS;
- ubuntu-24.04: SUCCESS;
- Golden Git configuration isolation: SUCCESS on both;
- verified PR HEAD: 7d9d84a.
