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
| executable file `100755` | ✅ covered by 5 executable/fileMode tests | ❓ | untracked has no index mode; decide whether the bit counts |
| empty file | ✅ DistinguishesDeletedAndEmptyTrackedFile | ❓ | |
| symlink to file `120000` | ❌ hashes target content, not link text | ❌ same | verified in WSL |
| symlink retargeted, same content | ❌ W does not change | ❌ | worst case: silent miss |
| dangling symlink | ❌ snapshot fails (`fatal`) | ❌ | legal Git state |
| symlink to directory | ❌ snapshot fails | ❌ | |
| symlink pointing outside repo | ❌ W depends on external file | ❌ | |
| gitlink / submodule `160000` | ❌ snapshot fails (`hash-object` on directory) | ➖ | verified on Windows |
| nested repository | ➖ | ❌ listed as `dir/`, snapshot fails | hits main checkout via `.claude/worktrees/` |
| linked worktree inside worktree | ➖ | ❌ same as nested repository | |
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
| commit with identical tree | ≠ | = | ≠ | = | ❓ |
| checkout another branch | ≠ | ≠ | ≠ | ≠ | ❓ |
| touch file (mtime only) | = | = | = | = | ❓ runtime test missing; only static timestamp invariant exists |
| index stat refresh (`git status` without optional-locks guard) | = | = | = | = | ❓ |
| edit ignored file | = | = | = | = | ❓ |
| file ignored only by `.git/info/exclude` | = | = | = | 📝 | currently counted in W |
| symlink retargeted, same content | = | = | = | ≠ | ❌ |
| CRLF ↔ LF on disk, same blob | = | = | = | 📝 | byte-exact or Git-semantic? |
| Windows chmod | ➖ | ➖ | ➖ | ➖ | NTFS has no executable bit |

## 3. Configuration and environment independence

Snapshot identity must not depend on how the observer is configured.

| Input | Status |
|---|---|
| `status.renames` | ✅ FingerprintsDoNotDependOnStatusRenameConfiguration |
| `core.autocrlf` | ✅ FingerprintsDoNotDependOnCoreAutoCrlfConfiguration |
| `core.excludesFile` | ✅ FingerprintsDoNotDependOnCoreExcludesFile |
| `core.fileMode` | ✅ FileModeConfigurationDoesNotChangeExecutableWorkingTreeIdentityOnLinux |
| `core.symlinks` | ❓ |
| `core.ignoreCase` | ❓ |
| inherited `GIT_*` repository-local variables | ✅ Invariants/GitEnvironmentInvariantTests + drift test |
| console code page (e.g. 852) | ✅ CreateProcessStartInfo_PinsRedirectedGitOutputToUtf8 |

## 4. Repository kinds

| Repository | Status | Notes |
|---|---|---|
| SHA-1 | ✅ (all tests) | |
| SHA-256 | ✅ SupportsSha256Repository | |
| unborn HEAD (no commit yet) | ❌ `rev-parse --verify HEAD` fails | 📝 fail or represent? |
| detached HEAD | ❓ | covered in discovery, not in snapshot |
| linked worktree as the observed repo | ❓ | |
| shallow clone | ❓ | H is commit oid; likely fine |
| sparse checkout | ❓ | skip-worktree entries missing on disk |
| bare repository | ✅ Invariants/SnapshotBuild_ReturnsNoSnapshotForBareRepository | diagnostic, no snapshot |
| outside any repository | ✅ Invariants/SnapshotBuild_ReturnsNoSnapshotOutsideRepository | |

## 5. Paths and scale

| Case | Status | Notes |
|---|---|---|
| path with spaces | ❓ in snapshot | runner test exists |
| path with diacritics (`ž.txt`) | ❓ in snapshot | runner pins UTF-8 |
| path with leading `-` | ❓ | `--` separator is used |
| thousands of files | ❌ Windows 32 767-char command line | fix: `--stdin-paths` (needs stdin API, runner closes stdin) or batching |
| file changes during snapshot | ❓ | ~8 separate Git calls; no before/after consistency check |
| filename differing only in case | ❓ | Windows, `core.ignoreCase` |

## 6. Platforms

Tests named `…OnLinux` run only on Linux/WSL. Every row above must be green on
both Windows and Linux before P1.2 exit.
