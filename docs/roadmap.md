# Codelaxy — Roadmap

> Status: ratified, revision 7
>
> Scope: this repository. Supersedes the M0–M6 roadmap that lived inside
> `my-cpu-router`. That roadmap's ideas survive; its implementation does not.
>
> Companion document: `docs/architecture.md` — the invariants referenced here
> as `I1` to `I14` are defined there.

---

## Product decision

Codelaxy is intended for other people: developers working in C++, Python,
shell, and C# who commit to Git and cannot answer with certainty whether an
exact state was verified, by what, and whether that proof still holds.

CPU Router is the first real consumer, not the reason the tool exists.

---

## Phase status

```text
P0.0  Product contract freeze                          DONE
P0.1  Snapshot / Requirement / Evidence / Verdict /
      Provider vocabulary                              DONE
P0.2  Single MrProper authority                        DONE
P0.3  Canonical legacy launcher                        DONE
P0.4  Architecture and docs sync,
      standalone C#/.NET decision                      DONE

P1.0  Standalone repository + .NET solution            DONE
P1.1  Git process boundary                             DONE
P1.2  Snapshot engine                                  PLANNED
P1.3  Requirement / Evidence / Verdict engine          PLANNED
P1.4  Provider interface                               PLANNED
P1.5  CMake/CTest provider, wired explicitly           PLANNED
P1.6  dotnet test provider, wired explicitly           PLANNED
P1.7  Interface ratification                           PLANNED
P1.8  Configuration and project detection              PLANNED
P1.9  Trust model                                      PLANNED
P1.10 CPU Router integration — ROUTER UNFREEZES        PLANNED

P2.0  Evidence persistence and safe reuse              PLANNED
P2.1  C++ and C# completion providers                  PLANNED
P2.2  Python provider: pytest, ruff                    PLANNED
P2.3  Shell provider: shellcheck, shfmt                PLANNED
P2.4  Foreign-repository conformance suite             PLANNED
P2.5  CI, distribution, documentation                  PLANNED
P2.6  1.0                                              PLANNED
```

### Note on P0 statuses

P0 describes completed contract and migration work, most of it performed in
the legacy implementation inside `my-cpu-router`. `DONE` does not mean that
the historical Python or Bash implementation exists in this repository. It
does not.

### Why the adapters come before configuration

Two rules pull in opposite directions. A generic interface must not be frozen
until two different consumers have used it (I12), and no repository-declared
provider may run before configuration and trust exist (I10).

Both hold, because the first two adapters are wired explicitly in code and
tests rather than selected by repository configuration. The interface is
exercised, nothing from a repository is executed, and configuration is then
designed against an interface that has already survived two shapes.

### Coverage ownership

Every cell of the coverage table in `architecture.md` §6.1 is owned, either by
an adapter milestone or by a written `NOT_REQUIRED` policy (§6.2).

```text
             FORMAT   LINT     BUILD           TEST
C++          P2.1     P2.1     P1.5            P1.5
C#           P2.1     P2.1     P2.1            P1.6
Python       P2.2     P2.2     NOT_REQUIRED    P2.2
Shell        P2.3     P2.3     NOT_REQUIRED    open decision 2
```

`NOT_REQUIRED` cells are decided in the milestone that introduces that
language and are stated in output, never implied by absence (lesson 20).

C# `BUILD` is owned by P2.1, not P1.6. `dotnet test` compiles internally, but
that produces no build evidence and satisfies no `BUILD` requirement (I14).

---

## P1.1 — Git process boundary

Status: DONE

### Goal

A reliable, isolated way to ask Git questions, on Windows and Linux, without a
shell and without inheriting the caller's Git context.

### Scope

- `GitProcessRunner` using `ProcessStartInfo` and `ArgumentList` (I6);
- environment isolation removing at least `GIT_DIR`, `GIT_WORK_TREE`, and
  `GIT_INDEX_FILE` (I5);
- repository discovery: worktree root and common Git directory, so tools work
  from any subdirectory;
- boundary failures reported in this layer's own terms (I13): Git missing,
  process launch failure, and "not inside a worktree" are diagnostics that end
  the run. They never become an evidence state, because at that point no
  snapshot exists and no provider has been asked anything;
- bare repositories are not verification targets in P1; they terminate with a
  Git-boundary diagnostic. `IsBare` is observed in order to produce that
  diagnostic, not in order to verify anything;
- cancellation and timeout, so a gate cannot hang on a command waiting for
  input;
- read-only invocations avoid touching the index.

### Non-happy-path coverage required

```text
missing git executable
working directory containing spaces
argument containing spaces
running outside any repository
bare repository
poisoned GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE
detached HEAD
```

### Exit criteria

- every test that requires repository state creates its own temporary
  repository; no test reads or mutates repository state of the Codelaxy
  development repository;
- the poisoned-environment test fails if isolation is removed;
- no code path constructs a shell command line;
- a missing Git executable produces a diagnostic, not an exception and not an
  evidence state;
- a bare repository produces a diagnostic naming that reason;
- Git's own answers are used verbatim, with no path rewriting (I4).

---

## P1.2 — Snapshot engine

Status: PLANNED

### Goal

One authoritative description of the exact state being judged.

### Scope

- deterministic fingerprints of HEAD, index, and working tree;
- staged snapshot identity independent of unstaged and untracked content;
- representation of ordinary, rename, copy, deletion, untracked, and unmerged
  states;
- schema-versioned serialization with deterministic encoding;
- one truth: no consumer derives repository state independently.

### Exit criteria

- identical states produce identical fingerprints across runs and machines
  with the same Git version;
- a staged snapshot is unaffected by unstaged edits;
- no consumer parses Git output outside `Codelaxy.Git`;
- the serialized form round-trips and rejects unknown record types.

---

## P1.3 — Requirement, Evidence, Verdict engine

Status: PLANNED

### Goal

Decide what must be proven, whether existing proof is valid, and what the
verdict is — without knowing anything about tools.

### Scope

- record types and their schema version;
- the result model of `architecture.md` §5, implemented as six distinct
  concepts: provider run outcome, stored evidence record, evidence evaluation
  against the current identity, evidence origin, requirement outcome, and
  verdict;
- each evidence record proves exactly one requirement kind (I14) and carries
  the identity of the exact requirement it proves (I8);
- validity computed at evaluation time and never stored in the record;
- identity binding covering requirement identity, provider identity, provider
  version, provider configuration, and toolchain identity as independent
  fields (I8);
- explainability: every decision names the facts that produced it;
- conservative defaults (I2).

### Exit criteria

- no input combination produces a granted verdict from missing information;
- `REUSED` + `FAILED` and `EXECUTED` + `PASSED` are both representable;
- changing only the adapter version invalidates reuse; changing only the tool
  version invalidates reuse; the two are distinguishable in the explanation;
- evidence for one requirement kind never satisfies another;
- two requirements of the same kind but different identities never satisfy
  each other;
- `NOT_REQUIRED` is reachable without fabricating an evidence record;
- an `UNKNOWN` evaluation forces fresh verification and never satisfies;
- the engine compiles and is tested with no provider present (I1).

---

## P1.4 — Provider interface

Status: PLANNED

### Goal

The contract between Codelaxy and the outside world. Designed here, ratified
in P1.7 (I12).

### Scope

- the interface from `architecture.md` §7, including the separation of
  `providerVersion()` and `toolchainIdentity()`;
- the contract is described in terms of identities, capabilities, and results
  without naming a .NET type; the first implementations are in-process C#
  adapters, while out-of-process support remains open decision 5;
- explicit registration of adapters in code; no repository-driven selection
  yet (I10), and before trust exists those adapters run only against controlled
  development or test fixtures;
- the boundary check: an automated test failing if a tool invocation, a
  file-name convention, or a source discovery rule appears in the core (I1).

### Exit criteria

- the interface is documented well enough to write an adapter from it alone;
- the boundary check fails when a tool invocation is added to the core;
- a provider that cannot report all three identities cannot be registered;
- a result for an undeclared requirement kind is rejected (I14);
- the public provider contract can be described without reference to a .NET
  assembly type or .NET-specific transport;
- the interface is marked provisional, not stable.

---

## P1.5 — CMake/CTest provider

Status: PLANNED

### Scope

- one adapter declaring and satisfying `BUILD` through `cmake --build` and
  `TEST` through `ctest`;
- reporting of provider identity, adapter version, toolchain identity, and
  configuration fingerprint;
- `UNUSABLE` when CMake or CTest is absent or misconfigured;
- wired explicitly, not selected by repository configuration.

`FORMAT` and `LINT` for C++ are not part of this adapter; they arrive in P2.1.

### Exit criteria

- a verdict can be produced for a CMake project without the core knowing what
  a compiler is;
- absence of the tool yields `UNUSABLE`, which denies rather than skips;
- the adapter contains no validity logic (`architecture.md` §7).

---

## P1.6 — dotnet test provider

Status: PLANNED

### Why this phase exists

One provider cannot show whether the interface is general. The second one is
cheap, because this repository's own tests are the target, and it exposes
every place where the interface bent around CMake.

Scope is deliberately narrow: `TEST` only. `dotnet build` and `dotnet format`
are separate capabilities and arrive in P2.1.

### Scope

- a `dotnet test` adapter declaring and satisfying `TEST`, wired explicitly;
- corrections to the P1.4 interface where C++ assumptions leaked in.

### Exit criteria

- the same requirement kind is satisfied by two unrelated providers through
  identical core code paths;
- no `BUILD` evidence is produced, despite the tool compiling internally
  (I14);
- every interface change is recorded as a defect of the P1.4 design, never as
  a special case for .NET.

---

## P1.7 — Interface ratification

Status: PLANNED

### Scope

- the provider interface is marked stable and versioned;
- the differences found in P1.6 are documented as design history;
- the adapter authoring guide is written from the ratified interface;
- ratification covers a contract described without naming a .NET type; whether
  providers ever run out of process remains open decision 5.

### Exit criteria

- the interface has a version number;
- the ratified contract is describable without naming a .NET type;
- a third adapter could be written from the guide without reading the core.

---

## P1.8 — Configuration and project detection

Status: PLANNED

Now safe to design: the interface has survived two consumers.

### Scope

- repository configuration declaring providers and requirements, never
  commands;
- a versioned schema from the first released version;
- `NOT_REQUIRED` policies expressible in configuration, so a non-applicable
  cell is a stated decision rather than an omission (§6.2);
- detection that proposes configuration and writes nothing without explicit
  confirmation;
- rejection of recipe-shaped configuration with an explanation of the
  boundary.

### Exit criteria

- a configuration containing a command line is rejected;
- a declared provider that is missing produces denial, never a skip;
- a requirement with neither a provider nor a `NOT_REQUIRED` policy denies;
- an unrecognized project reports that nothing can be proven, clearly;
- configuration may be parsed and explained, but before P1.9 neither provider
  selection nor `NOT_REQUIRED` policy from the repository may contribute to a
  `GRANTED` verdict;
- nothing from configuration is executed yet, pending P1.9.

---

## P1.9 — Trust model

Status: PLANNED

This is the gate that I10 requires before any repository-declared provider
runs. It cannot be added later: a release without it teaches first users an
unsafe habit.

### Scope

- per-worktree trust, recorded outside the worktree;
- observation allowed while untrusted, verification not;
- trust revoked when configuration changes, until reconfirmed;
- configuration from staged or incoming content never self-activates;
- only after this milestone may a provider be selected by configuration.

### Exit criteria

- a hostile configuration executes nothing without explicit trust;
- an untrusted configuration cannot obtain `GRANTED` by declaring every
  requirement `NOT_REQUIRED`;
- editing the configuration revokes trust;
- the untrusted path is covered by tests.

---

## P1.10 — CPU Router integration

Status: PLANNED

### Unfreeze condition

```text
CPU Router unfreezes when external Codelaxy can produce a valid Verdict
for a CPU Router staged Snapshot through the CMake/CTest provider.
```

Nothing else is part of the condition. Retiring legacy scripts and tuning gate
performance are valuable and may happen after the router is open again.
Folding them in would recreate the moving target this milestone exists to
remove.

### The integration exception to the freeze

CPU Router cannot satisfy its own unfreeze condition while frozen, because it
has no CMake build yet. The freeze is therefore lifted narrowly:

```text
On entering P1.10, exactly one dedicated integration branch of CPU Router
is permitted, for Codelaxy and CMake integration only.
Ordinary router development stays frozen until the first valid Verdict.
```

Commits on that branch that are not integration work are a violation of the
freeze, not a grey area.

### Scope

- on the integration branch: CMake, Ninja, and ccache adopted, which is also
  the fix for the gate that made commits unbearable (I11);
- CPU Router declares its requirements and providers to external Codelaxy;
- a verdict for a staged CPU Router snapshot produced end to end.

Note: the router's existing `format-check` has no equivalent until P2.1. Until
then its gate covers `BUILD` and `TEST` only, and that reduction is stated in
the integration pull request rather than quietly absorbed.

### Follow-up work, after the unfreeze

- retire `verify.sh` and the four shell tools in that repository;
- resume the frozen router defect list (P0.5.7, P0.6);
- gate performance tuning.

---

## P2.0 — Evidence persistence and safe reuse

Status: PLANNED

### Scope

- evidence records stored outside the working tree, published atomically;
- an interrupted producer never publishes a record that evaluates as `VALID`;
- origin reported explicitly as `EXECUTED` or `REUSED`;
- deleting the store causes fresh verification and touches neither source nor
  history.

### Exit criteria

- a second run with no changes performs no external work;
- changing either the adapter version or the tool version invalidates reuse,
  with no source change;
- a partially written record evaluates as `INCOMPLETE`, never as `VALID`;
- concurrent and crashed producers cannot publish evidence another process
  accepts.

---

## P2.1 — C++ and C# completion providers

Status: PLANNED

Closes every remaining cell for the two languages that already have adapters,
and restores the formatting capability CPU Router had before integration.

### Scope

```text
C++ FORMAT   clang-format
C++ LINT     compiler-warning policy, declared as LINT
C#  FORMAT   dotnet format
C#  BUILD    dotnet build
C#  LINT     configured analyzers
```

- check semantics only: formatters run in verification mode. Normalization
  remains MrProper's authority and is never triggered by a provider;
- `C# BUILD` is a declared capability with its own evidence, separate from the
  `TEST` adapter of P1.6 (I14).

### Exit criteria

- a formatting violation denies with the offending files named;
- no provider modifies a file;
- `BUILD` evidence for C# exists independently of any test run and is reusable
  on its own;
- the C++ and C# columns of the §6.1 table have no cell without an adapter.

---

## P2.2 — Python provider

Status: PLANNED

### Scope

- `pytest` adapter satisfying `TEST`;
- `ruff` adapter satisfying `LINT` and `FORMAT`, declaring both;
- `BUILD` covered by an explicit `NOT_REQUIRED` policy for Python, written
  down and visible in output;
- interpreter and environment reported as part of toolchain identity, because
  the same code under two interpreters is not the same evidence.

### Exit criteria

- a Python-only repository reaches a verdict with `BUILD` reported as
  `NOT_REQUIRED` and the reason stated;
- changing the interpreter version invalidates reuse;
- both adapters satisfy the adapter rule.

---

## P2.3 — Shell provider

Status: PLANNED

The language that tests whether `NOT_REQUIRED` is honest, because shell has no
build step and no dominant test framework.

### Scope

- `shellcheck` adapter satisfying `LINT`;
- `shfmt` adapter satisfying `FORMAT`;
- `BUILD` covered by an explicit `NOT_REQUIRED` policy;
- `TEST` resolved by open decision 2: either a `bats` adapter or a written
  `NOT_REQUIRED` policy. Leaving it undecided is not an option at this point.

### Exit criteria

- a shell-only repository reaches a verdict;
- `NOT_REQUIRED` appears in output as a normal result with an explanation, and
  is distinguishable from a skipped or missing check;
- no core change was needed to add this language, or every change that was
  needed is recorded as an interface defect (I12).

---

## P2.4 — Foreign-repository conformance suite

Status: PLANNED

The phase that decides whether "general" was true.

### Scope

Automated runs against real third-party repositories:

```text
a small C++ project using CMake and CTest
a Python project using pytest
a shell-heavy project using shellcheck
a .NET project
a project with no recognizable providers
a project with a deliberately hostile configuration
```

### Exit criteria

- the normal projects reach a verdict with no change to Codelaxy;
- the unrecognized project denies, clearly and without guessing;
- the hostile project executes nothing;
- every assumption inherited from CPU Router has been found and removed.

---

## P2.5 — CI, distribution, documentation

Status: PLANNED

### Scope

- the gate runs in CI on every pull request, publishing evidence and verdicts,
  so a claim can quote a record (I9);
- distribution decided and implemented, per open decision 1;
- documentation: install, initialization, configuration reference, adapter
  authoring guide, trust model, and an explicit statement of what Codelaxy is
  not;
- the adapter guide validated by someone writing an adapter from it alone.

### Exit criteria

- install to first verdict in under five minutes on a clean machine;
- `main` has no failing checks;
- a third adapter is written using only public documentation.

---

## P2.6 — 1.0

```text
every applicable cell of the coverage table has an adapter,
  and every non-applicable cell has a written NOT_REQUIRED policy
configuration, detection, trust
real evidence reuse for at least one requirement kind
conformance suite green
one-command install
documented, versioned adapter interface
```

### Explicitly after 1.0

```text
Entity model and impact graph
fine-grained reuse below entity boundaries
MrProper machine-readable reporting
StatusMan evidence view
additional languages and providers
```

---

## Working rules

- One logical change, one commit, explicit staging, no blind `git add .`, no
  `--no-verify`.
- No claim that tests passed until the output has been seen.
- Expensive proof is not repeated when nothing relevant changed — and the
  cheap checks never wait for the expensive ones (I11).
- A milestone is done when its exit criteria are demonstrably met, not when
  the code exists.
