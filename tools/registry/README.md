# Roadmap Registry tooling (experimental, phase 2 / S0 + S1)

Small, auditable building blocks of the roadmap registry. Python standard library only (no third-party dependency). Nothing here is wired into the
production repository, CI or any ratified document; it was built in an isolated sandbox branch.

## Layout

| Path | What |
|---|---|
| `clxreg/protect.py` | protected-files guard: SHA-256 manifest of files that must never change; refuses staged protected files |
| `clxreg/canon.py` | canonical JSON (UTF-8, LF, 2-space indent, code-point-sorted keys, integers only), digests, strict reader |
| `clxreg/store.py` | `records/{REQ,SCN,EVD,MIL}/<ID>.json`: ID shape, layout, `next-id`, check against a base ref (nothing is ever deleted or renamed) |
| `clxreg/textsource.py` | literal label / quote search and range parsing in source text (no interpretation) |
| `clxreg/sources.py` | catalog of source documents: pinned versions, files verified against their SHA-256, literal quotes, status transitions |
| `clxreg/namespaces.py` | catalog of label namespaces (pattern, authority, `distinct_from`) |
| `clxreg/aliases.py` | historical labels attached to permanent IDs, each with a namespace and a documented source; resolution; alias moves |
| `clxreg/units.py` | addressable units of a source: text lines (split at LF only) and ODS paragraphs; explicit `UnsupportedSource` instead of partial reads |
| `clxreg/patterns.py` | label patterns from the namespace catalog, ranges (never expanded), second pass for label-like tokens, ambiguity rules |
| `clxreg/literals.py` | IMP2-07a: original states, references and result phrases recorded literally, never interpreted |
| `clxreg/ledger.py` | the import ledger: build / verify / diff; every occurrence located, literal, with an explicit disposition |
| `clxreg/candidates.py` | dry-run generator of candidate aliases from a ledger and an approved mapping, into a new directory only |
| `clxreg/localcat.py` | documented, reproducible build and check of the machine-local catalogs (every claim with a literal basis) |
| `catalog-specs/` | the specs of the real MICROMAP corpus (sources, namespaces, ambiguity rules, run); see its README |
| `scripts/verify-python-versions.ps1` | isolated run of the suite on other Python versions (downloads interpreters; needs the owner's consent) |
| `tests/` | unit and integration tests (`python -m unittest discover -s tests -t .`) |
| `mutation/` | targeted text-mutation harness (`python mutation/run_mutants.py mutation/specs/<name>.json`) |
| `local/` | machine-local data (protected manifest, real source catalog); not part of any patch |

## Commands

```text
python -m clxreg.protect  check --manifest M [--repo R] [--root key=dir]
python -m clxreg.store    check --root DIR [--base REF]      |  next-id TYPE --root DIR [--base REF]
python -m clxreg.sources  check --catalog F [--root key=dir]... [--old-catalog F]
python -m clxreg.aliases  check --root DIR --namespaces F --catalog F [--source-root key=dir]... [--base REF]
```

```text
python -m clxreg.ledger     build --run R --catalog C --namespaces N [--ambiguity A] [--mapping M] [--root key=dir]... --out L
python -m clxreg.ledger     verify --ledger L --catalog C [--root key=dir]... [--run R --namespaces N [--ambiguity A] [--mapping M]]   (the last group rebuilds and compares)
python -m clxreg.ledger     diff L1 L2
python -m clxreg.candidates generate --run R --catalog C --namespaces N --mapping M --store-root DIR [--ambiguity A] [--root key=dir]... --out NEWDIR
python -m clxreg.localcat   build-sources --spec S --manifest PM [--root key=dir]... --out C
python -m clxreg.localcat   check --spec S --manifest PM --catalog C --namespaces N [--root key=dir]...
```

Exit codes: 0 no blocking finding, 1 data error found, 3 the check could not be carried out (bad arguments, unreadable file, bad ref).

## Finding codes used

`DE-01` duplicate id/key · `DE-02` malformed (ID, name, directory, schema, canonical form) · `DE-03` unknown reference ·
`DE-05` namespace / pattern / duplicate alias · `DE-06` record, version or alias removed, changed or moved against the base ·
`DE-12` conditional field missing or misplaced · `DE-13` contradiction with the pinned source (hash, quote, literal label, status without source) ·
`AD-01` same string in two namespaces without `distinct_from` · `AD-04` weak pinning or source not available here (the check was skipped, not passed) ·
`PR-01..04` protected files.

Ledger `build` exits 0 (complete), 1 (problems: a source changed, a mapping that cannot be applied), 2 (incomplete: a source missing or unsupported), 3 (inputs unusable or the output exists).

## What the ledger guarantees (S1)

Every occurrence it records has the identity and SHA-256 of the pinned source, an exact location (unit, column, length), the literal unnormalised text, the
historical namespace and original label, and an explicit disposition from a closed set. Original states, references and result phrases are recorded
literally (IMP2-07a). A string that two namespaces claim stays ambiguous; a range stays a range (its members are never created); a match inside a longer one
is kept inside it; a label-like token no namespace claims is reported; nothing is dropped, merged or given an identity by the tool. Missing, unsupported,
excluded or changed sources are stated in the ledger and in the exit code. The import is read-only and deterministic (byte-identical on Windows and Linux).

## What the evidence model guarantees (S2 libraries; integrated CLI added in S4)

`clxreg.dirty` (content manifests of a dirty git tree or of a plain tree; no mtimes, no order, `bin`/`obj` exclusions recorded), `clxreg.provenance`
(the six points that must all be proven before a DIRTY run may be PROVISIONAL), `clxreg.testrun` (reads TRX files and `gitrun` audit records into facts and
*candidate* evidence; never a verdict, never an identity), `clxreg.evidence` (classes, qualification Q1-Q9, derivation, gate), `clxreg.freshness` (Q8 from
git, and propagation of a changed contract through `depends_on_revisions`).

* Only `COMMIT_BOUND` evidence (CLEAN tree, full commit hash, source available and hash-checked) can support `VERIFIED`. `PROVISIONAL` (DIRTY tree with a
  content fingerprint and all six provenance points proven) is listed in reports and never counted in `DONE` or in a gate. `UNBOUND`, `UNLOCATED` and
  `UNVERIFIED_RESULT` leave a named finding. The class is derived on every read, never stored.
* A suite-level PASS never proves a given test: the result of a candidate comes from the tests asked about, and a test that may have returned at a platform
  guard (the audit record's guard list is often truncated) is `UNVERIFIED`, not `PASS`.
* Missing, incomplete or changed evidence never creates success: a changed working copy, a missing TRX, a manifest taken after the run started, a
  platform mismatch, a git failure or an unresolved reference each end as `UNBOUND` / `UNLOCATED` / `UNDETERMINED` or as an error, with the reason named.
* Currency compares the evidence commit with a reference through the net `git diff --name-only --no-renames` and the scope globs of the requirement.
* Limits: git normalises line endings, so a manifest of a dirty tree is stable only with the fixed `core.autocrlf=false`; the existing `testrun` records
  were made without a manifest at run time, so they stay `UNBOUND` (PROVISIONAL is reachable only for future runs that capture a manifest first).

## What this does not do

* It does not prove that a ratification happened: a `RATIFICATION-RECORD` version is a pinned file, and adding one is a reviewed change.
* A label that no pattern recognises is invisible to it.
* A source that is not available in the running environment is reported as `AD-04`, never as success.
* Git hooks and local configuration are not a security boundary.
* Alias evidence is checked against UTF-8 text sources only. A label found only in an ODS is recorded in the ledger (with its cell address) but the candidate
  generator refuses to propose it.
* In the real MICROMAP namespace catalog `maps_to` is `EXTERNAL`: no general registry mapping of a namespace has been decided (TD-9, TD-10 are open). The narrowly authorized IMP2-16 pilot records literal RT1/RT3 and range-only RT2 without defining them.
* The recognition of states, references and result phrases is syntactic (IMP2-07a); telling a hash from a word or a legend OPEN from a state is deferred (07b).

## Completion: S2 repair, validator, pilot, generated views and CLI

Run `python -B -m clxreg --help` from this directory; each command's `--help` lists its input catalogs, explicit output and source roots. No command stages or commits. `check`, `dump-model`, `gate`, `next-id`, ledger verification/diff and `protect` read inputs only. Outputs from `export` and ledger build must be explicit and do not replace registry inputs. Export refuses existing outputs and writes strings as strings in FODS.

The S3 validator publishes `model/1`, reports the number of examined records, rejects empty selections and data errors, validates source references and revision history against a real Git base, and rehashes EVD artifacts under an explicit local artifact root before they can qualify. Missing or tampered artifacts cannot produce VERIFIED. `external_findings` are reported separately and cannot change Python's verdict. `schema/rules.json` is the tested rule catalog; `schema/registry.schema.json` describes the hand-validated stdlib record schema. Stored DEC entities remain unsupported; accepted decisions need explicit, source-proven attestations.

The pilot is experimental, not an interpretation of history: RT1/RT3 are literal aliases, RT2 is IMPLIED_BY_RANGE, all three definitions remain UNRESOLVED and their gate fails. Ambiguous historical R1/R3 occurrences remain in the lossless ledger rather than being silently assigned. Uncatalogued AUDIT-C aliases are not fabricated and no audit mutant is assigned to RT1–RT3. TD-9/TD-10 and placement decisions remain open.

S2 audit repairs normalize offset-bearing timestamps to UTC and require an explicit clock offset for naive timestamps; an unknown timezone never proves chronology. Content manifests reject symbolic links, Windows reparse points and nested repositories. Unknown persistence cannot bypass freshness. Active FAIL blocking was explicitly approved by the owner on 2026-11-02. Old runs remain UNBOUND; neither a later manifest nor a generated view repairs their provenance.

For CONTINUOUS/UNSPECIFIED requirements, Q8 is established only by live Git measurements from the explicitly configured `repo`/`ref`. Supplied `freshness` and equivalent-revision maps are never authoritative, including through CLI `--context`. Without usable Git evidence these requirements cannot become VERIFIED; ONCE retains its separate schema semantics.

## What a ledger does and does not prove

`validate_ledger()`, `complete: true` and `ledger verify` **without `--run`** check structure and the stated locations only. A success there does **not** prove that the inventory is complete: a ledger with an occurrence or a whole source removed can pass them. Only a rebuild (`ledger verify --run ...`) compares the ledger with a fresh import, and that proof is only as strong as the origin of the run, catalog, namespaces, ambiguity and mapping given to it; the digests stored in the ledger are claims of the ledger.

`pilot.build` has no unverified mode. It requires `run`, and explicit `ambiguity` and `mapping` (`None` only when the trusted import used none), and refuses a ledger that differs from their fresh import.

`export --ledger` remains usable as a view, but states what it is. The `REGISTRY-METADATA` rows `import_ledger_verification` (`NOT_VERIFIED`, or `REBUILD_MATCHED` when `--ledger-run`, `--ledger-ambiguity`, `--ledger-mapping`, `--catalog` and `--namespaces` are given; ambiguity and mapping take a path or `NONE`), `import_ledger_rebuild_inputs`, `import_ledger_complete`, `import_ledger_problems` and `import_ledger_sources_not_processed` are appended after the existing rows. A proven difference exits 4 without writing, a source the ledger claims as processed that cannot be read also exits 4 but is reported as unavailable, and missing or invalid verification inputs exit 1. An unreadable input file keeps the general exit 4.

Exit codes of the integrated CLI: 0 success, 1 invalid data, 2 unsatisfied gate, 3 refused overwrite, 4 missing/tampered/unreadable source. A valid unresolved pilot can pass `check` while failing `gate`; validation does not claim that unresolved requirements are fulfilled. Generated views are deterministic FODS/TSV outputs and never modify the original ODS. Their reference commit is a baseline, not a claim that these uncommitted registry files existed in it. The delivery manifest identifies actual bytes.


O1 audit correction: exports append two additional metadata keys after
all existing rows. `import_ledger_problem_details` is a canonical JSON array of
the complete ledger problem strings. `import_ledger_source_details` is a canonical
JSON array of non-processed source rows with their original SOURCE entries,
including reasons and exclusion decisions. Both are empty strings without a
ledger. This is an additive machine-readable output contract change; consumers
must accept additional metadata keys. Existing metadata positions are preserved.

Export publication writes and flushes a sibling temporary file, then atomically
creates the target using a hard link without replacement. A concurrent target
wins and is left unchanged. Unsupported filesystems fail safely without a target;
there is no overwrite-capable fallback. Disk write/flush failures leave no target
and the temporary file is removed. This does not claim power-loss durability of
the directory entry or defend against a hostile process replacing parent paths.


## Final ledger and scanner contracts

A source marked PROBLEM must carry at least one recorded problem. Incomplete
inventories are reported explicitly; structural verification without a trusted
run still does not prove that all expected sources and occurrences were included.
Malformed diff ledgers and source catalogs are rejected before unsafe field
access. Each CLI emits each ledger finding once. SOURCE changes have an explicit
source-level display instead of meaningless unit/column placeholders.

The two established CLI entry points retain their separate exit-code contracts:

| Situation | `python -m clxreg.ledger` | Integrated `python -m clxreg` |
|---|---:|---:|
| Clean verification | 0 | 0 |
| Malformed ledger/catalog structure (DE-02) | 1 | 1 |
| Missing/incomplete source inventory (AD-04 only) | 2 | 4 |
| Proven rebuild difference | 1 | 4 |
| Unusable input/JSON/IO | 3 | 1 for invalid data, 4 for unavailable IO/source |
| Existing output | 3 | 3 |

A diff returns 1 for a valid difference and 0 for equality; malformed diff inputs
are refused with 3 in the standalone CLI and 1 in the integrated CLI. Therefore
callers must select one documented interface rather than assume global numeric
interchangeability. In particular incomplete standalone verification no longer
returns 0: it prints INCOMPLETE and returns 2.

The scanner raises `patterns.ZeroWidthMatch(ValueError)` with an `offset` for a
zero-length match encountered in real input. Ledger import catches this type;
unrelated ValueError exceptions are not classified by matching their text.
Real scanner regressions run in bounded child processes. The mutation runner
rejects non-finite, nonpositive, boolean and None timeout values before work;
its CLI reports invalid timeout arguments as usage errors (exit 2).

Pilot input-shape failures use PilotError. A failed pilot directory write cleans
up only its own newly-created output directory; existing outputs are refused.
This cleanup is not atomic directory publication. Export file publication has
the stronger no-partial-target behavior documented above.

Portable CI deliberately points CLX_WORKSPACE_ROOT to an unavailable directory.
The real-source test helper reports that explicit condition before checking
machine-local catalogs, so a fresh clone and a local portable run have identical
precise skip reasons. The approved skip identities/count remain unchanged.


Accepted scenario adequacy must name the current requirement revision or a revision
whose editorial equivalence is established by the validator. An accepted old normative
binding cannot approve new merely asserted coverage. Relation-cycle detection visits
completed subgraphs once; detected cycles still block the global gate. In roadmap
exports, VERIFIED assertions use verification state and DONE assertions use effective
status, so a verified requirement can also be effectively DONE or BLOCKED without a
false disagreement about its verification.
