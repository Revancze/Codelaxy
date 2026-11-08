# RoadmapRegistry acceptance — 2026-11-08

The registry is an internal development tool, not a change to the Codelaxy application core.
This change closes O1–O9 while retaining the existing ledger/model schemas and the two
explicit CLI contracts. A separate local auditor reviewed the runtime implementation,
rehash-verified all 114 release files, and issued GO with no remaining source blocker.
The reviewed manifest SHA-256 is
`f8c021b57d9b554e0be1f4378904da32563bf8994ced3844cf55fc043721b04f`.
This document was added after the source audit and is not one of those 114 files.

## Resulting behavior

| Finding | Resolution |
|---|---|
| O1 | Pilot requires a trusted run and explicit trusted ambiguity/mapping; a fresh rebuild is mandatory. Export distinguishes REBUILD_MATCHED/NOT_VERIFIED. Mismatch refuses export; verified metadata is computed, not asserted by the ledger. |
| O2 | PROBLEM requires a recorded problem. Missing/unsupported inventory is explicit and nonzero in verification. Export preserves completeness, nonprocessed source identity/status and full available problem/source reasons. |
| O3 | Malformed diff ledgers and source catalogs are rejected before unsafe access, including with --run; malformed input does not become a forged-ledger mismatch. |
| O4 | Changed SOURCE entries have an explicit source-level display. |
| O5 | Ten supplemental mutations separately exercise ledger shape diagnostics and Git-base revision decrease/history deletion. These are diagnostic/control coverage, not ten newly discovered trust bypasses. |
| O6 | Scanner guard removal is mutation-tested with bounded real scanner children; all runner timeouts must be finite and positive. |
| O7 | Verification emits structural findings once. |
| O8 | Incomplete standalone verify no longer succeeds. Established standalone/integrated numeric contracts remain intentionally distinct and are documented in the registry README. |
| O9 | ZeroWidthMatch carries a stable type/offset; import catches that type. Real source scans test the error path without a scanner mock. |

Export file publication writes and flushes a sibling temporary file, then creates the
final target without replacement through a hard link. Write, short-write, flush and
stream-open failures clean up the temporary file; a concurrent target is preserved.
Filesystems without hard-link support fail safely. Pilot directory writes clean up
only their own new directory on failure; this is not atomic directory publication.

The export contract adds seven metadata rows after all original metadata: verification,
proven input digests, completeness, problem count, nonprocessed source status, full
problem details and source details. The last two are canonical JSON arrays. Existing
positions/sheets/columns remain unchanged, but serialized export bytes and hashes change.
External consumers must accept additive metadata keys; no claim is made about unknown
external consumers.

## Verification

- Windows CPython 3.14.10: full registry gate **852 PASS, 0 SKIP**, no failures/errors.
- Ubuntu on actual WSL2 Linux, CPython 3.14.4: portable gate **822 PASS, 30 approved SKIP**,
  no failures/errors. Skip identities and reasons are checked exactly; none were added.
- The 852 count was saved in CI/gate/policy only after a real passing 852-test run.
- The complete shipped mutation catalog has 28 specs / 699 IDs. The release coordinator
  retains per-ID JSON, baseline results and spec hashes; declared equivalent and
  platform-specific outcomes are reported separately from killed mutants.
- The final code received independent targeted checks (94 tests), an independent final
  23-test rerun, and 107 malformed-ledger plus 10 malformed-catalog probes without raw
  exceptions. Reruns are not additional unique test counts.
- The four existing PR review themes were checked: INITIAL only on first revision;
  no rollback/deletion of base history; every occurrence has an inventory source;
  zero-width matches cannot keep the scanner at the same position indefinitely.

Reproduce the portable CI check with Python 3.12 and .NET from global.json installed:

```sh
python -B -X utf8 -W error tools/ci/registry_gate.py --expected-tests 852 --expected-skips 30 --skip-policy tools/ci/registry-portable-skips.json
```

Set CLX_WORKSPACE_ROOT and CLX_TESTRUN_ROOT to unavailable paths for that profile.
Fresh clones do not contain machine-local catalogs; the explicit unavailable-workspace
condition is detected first so exact skip reasons are stable in a real CI environment.
A local full run needs those catalogs and historical source/testrun roots.

Run a mutation spec from tools/registry, for example:

```sh
python -B -X utf8 mutation/run_mutants.py mutation/specs/scanner-guard.json --timeout 60 --json scanner-results.json
```

Every mutation baseline must pass. A hanging baseline is an error, not successful
mutation evidence. CLI timeout parsing rejects NaN/infinity/zero/negative durations;
library APIs also reject None and booleans.

## Boundaries

Trust depends on the origin of supplied run/catalog/namespaces/ambiguity/mapping/roots;
ledger digests alone are claims. Verification without --run does not establish inventory
completeness. NOT_VERIFIED exports remain views, not proof. Old historical evidence is
not retroactively upgraded by these changes. Local WSL testing is not GitHub Actions;
merge requires successful Windows and Ubuntu CI on the actual pushed commit.
