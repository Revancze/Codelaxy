# Codelaxy — Architecture Contract

> Status: ratified, revision 7
>
> Scope: this repository (`Revancze/Codelaxy`). The historical Python/Bash
> implementation inside `my-cpu-router` is a source of lessons, not a base.
>
> This document states what Codelaxy is, what it must never become, and which
> mistakes are not allowed to happen twice. Every rule here was paid for.

---

## 1. What Codelaxy is

Codelaxy answers one question about one exact state of a repository:

> What has already been proven, for which exact state, by which authority, and
> is that proof still valid?

It decides **what must be proven**, **whether valid proof already exists**, and
**what the verdict is**. Providers decide **how fresh proof is produced**.

```text
valid proof exists            REUSE
validity cannot be proven     VERIFY AGAIN
verification fails            NO SUCCESSFUL VERDICT
```

Codelaxy is Git-native. Git is not a provider and not an interchangeable
implementation detail; it is the assumed version control system.

## 2. What Codelaxy is not

Codelaxy is not a build system, task runner, test framework, formatter, linter,
dependency resolver, or CI platform. It never owns compile commands, link
commands, build recipes, or test-framework semantics.

If a proposed feature teaches the core how to build, link, compile, run a
recipe, or replace a provider, it does not belong in the core.

---

## 3. Invariants

These are binding. A change that breaks one is a defect regardless of which
milestone it serves.

### I1 — The core knows no language

No file in `Codelaxy.Core` or `Codelaxy.Contracts` may contain a tool
invocation, a file-name convention (`*_test.cpp`, `tests/`), a source
discovery rule, or an assumption that a particular configuration file exists.

Language knowledge lives in adapters only.

### I2 — Uncertainty may only expand verification

Missing, unknown, malformed, stale, incomplete, corrupt, conflicting, or
unverifiable evidence never satisfies a requirement. If validity cannot be
proven, reuse is forbidden.

There is no path from "we do not know" to `PASS`.

### I3 — Validate before mutating

An operation either completes or leaves the previous state untouched. Nothing
half-applies and then discovers a problem.

Source of this rule: the router's `commitPath` used to overwrite a foreign
net's cell and only afterwards have no way to report it.

### I4 — Git is the authority on Git

Paths, branches, and repository state come from Git's own answers. Nothing
corrects, rewrites, or guesses them with string manipulation.

Source of this rule: `C:\msys64\tmp` versus `C:\tmp`. The fix was to stop
arguing with Git, not to add another translation layer.

### I5 — Git runs in an isolated environment

Before every Git invocation, the inherited environment is stripped of the
variables that would redirect it at another repository — at minimum `GIT_DIR`,
`GIT_WORK_TREE`, and `GIT_INDEX_FILE`.

This is enforced by a test that deliberately poisons all three.

### I6 — Processes are started directly

Git and providers are started through `ProcessStartInfo` with `ArgumentList`.
No shell, no `sh -c`, no PowerShell intermediary, no manual quoting.

### I7 — A timestamp is not proof

Timestamps may be recorded as diagnostics. They never establish identity,
equivalence, validity, or reuse eligibility.

### I8 — Evidence is bound to identity

Reuse validity depends on the snapshot, the relevant inputs, the exact
requirement identity, the evidence schema version, and three separate
identities that are never collapsed into one:

```text
requirement kind + requirement identity  what exact proof was requested
provider identity + provider version     the adapter itself
provider configuration fingerprint       how the adapter was configured
toolchain identity                       the external tool and its version
```

Requirement kind is not sufficient identity. Two requirements may both be
`TEST` while referring to different scopes, suites, or policy parameters.
Evidence for one must never satisfy the other.

Adapter version 2 may produce different evidence from adapter version 1 over
the same CMake 4.4. Tool version 4.5 may produce different evidence from 4.4
under the same adapter. Both changes must invalidate reuse independently.

A provider that cannot report all three provider-side identities cannot produce
evidence.

### I9 — A proof only its author can reproduce is not proof

A verdict produced solely on one machine, with nothing recorded about what
produced it, is an unauthenticated bare PASS.

### I10 — Nothing declared by a repository runs before configuration and trust

Repository configuration names providers to execute. Executing them means
executing code chosen by whoever wrote that repository.

```text
No repository-declared provider may be executed before both
configuration semantics and trust semantics exist.
```

A worktree is untrusted until the user says otherwise; an untrusted worktree
may be observed but never verified. Configuration arriving from staged or
incoming content never self-activates.

Adapters wired explicitly in code or tests are not repository-declared and are
not covered by this rule. That is how the provider interface is exercised
before configuration exists.

Before trust semantics exist, explicitly wired providers may run only against
controlled development or test fixtures, never as an end-user verification
path for an arbitrary worktree.

Repository-derived policy is also inert before trust. An untrusted
`NOT_REQUIRED` declaration may be observed and explained, but it cannot
contribute to a `GRANTED` verdict.

### I11 — The gate must be usable

A verification gate that makes a developer afraid to commit has failed,
regardless of how correct it is. Expensive and cheap checks are separated by
design, not patched apart after it starts hurting.

Source of this rule: the router's commit gate, where `verify.sh` recompiled
roughly 15 sources for each of 11 tests — about 154 translation units and 11
links for every commit, with no reuse of any kind.

### I12 — Generic interfaces are frozen by use, not by design

A generic interface may be designed before its first consumer. It may not be
declared stable until at least two materially different consumers have
exercised it, and every change made for the second consumer is recorded as a
defect of the original design rather than as a special case.

This replaces the blunter rule "do not design an API before there is a
consumer", which would have forbidden designing the provider interface at all.

### I13 — Infrastructure failure is not a verification result

A failure to observe the repository at all — Git missing, Git failing to
start, not being inside a worktree — produces no snapshot, no evidence, and no
verdict. It is reported as a diagnostic and the run ends.

Such a failure must never be expressed as an evidence status. Evidence states
describe what a provider produced; the absence of Git means nothing was ever
asked of a provider.

A bare repository has no worktree and is therefore not a verification target.
It terminates at the Git boundary with a diagnostic, like any other case in
this invariant.

### I14 — One requirement kind is never satisfied as a side effect of another

A provider satisfies exactly the requirement kinds it declares in
`capabilities()`. Work that a tool happens to perform internally does not
satisfy a requirement nobody asked it to prove.

`dotnet test` compiles before it runs tests. That does not make it a `BUILD`
provider: no build evidence was requested, none was recorded, and none can be
reused. A `TEST` result is evidence about tests and nothing else.

---

## 4. Vocabulary

Fixed. A third name for any of these is a defect.

```text
Snapshot      the exact state being judged
Requirement   what must be proven for a decision, never how
Evidence      an immutable record of verification, bound to identity
Verdict       the decision for one exact Snapshot
Provider      the component that produces fresh evidence
```

Reserved for later, not part of the 1.0 data model:

```text
Entity        a generic unit a provider asserts about, used by the impact
              graph after 1.0. Reserved so the word is not taken for
              something else in the meantime.
```

---

## 5. Result model

Six distinct concepts. Collapsing any two of them is a modelling error.

### 5.1 Provider run outcome

What happened when a provider was asked to produce evidence. This is not
stored; it is the immediate result of a run.

```text
PASSED     verification ran and passed
FAILED     verification ran and did not pass
UNUSABLE   the provider could not produce a trustworthy result
           (tool missing, misconfigured, output not understood)
```

`PASSED` and `FAILED` both produce an evidence record. `UNUSABLE` produces
none: there is nothing trustworthy to record.

### 5.2 Evidence record

Immutable, stored. The record carries what the provider observed, together
with the identity it is bound to (I8), and the single requirement kind it
proves (I14).

```text
result               PASSED | FAILED
requirementKind      the one requirement kind this record proves
requirementIdentity  fingerprint of the exact requirement, including scope
                     and policy parameters that affect what was requested
identity             snapshot, inputs, provider identity and version,
                     provider configuration fingerprint, toolchain identity,
                     evidence schema version
```

`requirementKind` controls capability matching. `requirementIdentity` controls
whether evidence can satisfy this exact requirement. Two records may both be
`TEST` evidence and still be non-interchangeable.

Nothing about validity is stored in the record. Validity is not a property of
a record; it is a relationship between a record and the state being judged.

### 5.3 Evidence evaluation

Computed when a stored record is considered for the state being judged now.

```text
VALID        the record applies to this identity and is whole
INVALID      the record does not apply to this identity
INCOMPLETE   the record is damaged or partially written
UNKNOWN      applicability cannot be established
```

Only `VALID` permits reuse. Everything else, including `UNKNOWN`, forces fresh
verification (I2). A `VALID` record whose result is `FAILED` is proof of
failure, and denies.

### 5.4 Evidence origin

How the evidence backing a requirement was obtained in this run.

```text
EXECUTED   obtained now, from a provider
REUSED     an existing record was evaluated VALID and reused
```

Origin and result are independent: `REUSED` + `FAILED` is a normal, expected
combination and must be representable.

### 5.5 Requirement outcome

The result of evaluating one requirement. Not itself evidence.

```text
SATISFIED      valid evidence exists and its result is PASSED
UNSATISFIED    valid evidence does not exist, or its result is FAILED
NOT_REQUIRED   policy proves this requirement does not apply
```

`NOT_REQUIRED` is a first-class successful outcome, not a silent skip, and
carries no evidence record. Shell projects have no build step; that is the
case this outcome exists for.

### 5.6 Verdict

```text
GRANTED   every applicable requirement is SATISFIED or NOT_REQUIRED
DENIED    anything else, with the reason named
```

Worked example, requiring no special handling:

```text
REUSED + record.result = FAILED + evaluation = VALID
    → requirement UNSATISFIED
    → verdict DENIED
```

---

## 6. Requirement kinds

The core knows a closed set. Mapping to tools belongs to adapters.

```text
FORMAT   source matches its declared format
LINT     static analysis reported no policy violation
BUILD    the declared artifact can be produced
TEST     the declared tests passed
CUSTOM   anything else a provider can evidence
```

### 6.1 Coverage table for 1.0

| Requirement | C++ | Python | Shell | C# |
|---|---|---|---|---|
| FORMAT | clang-format | ruff format | shfmt | dotnet format |
| LINT | compiler-warning policy | ruff | shellcheck | configured analyzers |
| BUILD | CMake | `NOT_REQUIRED` | `NOT_REQUIRED` | dotnet build |
| TEST | CTest | pytest | bats, or `NOT_REQUIRED` | dotnet test |

### 6.2 The coverage rule

```text
Every applicable cell has an owning adapter and an owning milestone.
Every non-applicable cell has an explicit NOT_REQUIRED policy.
No cell may remain unexplained.
```

An unexplained cell is a gap, not an aspiration. `NOT_REQUIRED` is a decision
that must be written down and visible in output; it is never the absence of a
decision.

The roadmap names the milestone that owns each cell.

### 6.3 Multi-kind adapters

A single adapter may satisfy several kinds, and must declare each one it
satisfies. The CMake/CTest provider satisfies `BUILD` through `cmake --build`
and `TEST` through `ctest`, and declares both.

An adapter never satisfies a kind it did not declare, whatever its tool does
internally (I14).

Adding a sixth requirement kind requires a written reason in this document.
Growth of this list is how a generic core becomes a pile of special cases.

---

## 7. Provider interface

```text
identity()             stable provider name, e.g. "cmake-ctest"
providerVersion()      version of this adapter
toolchainIdentity()    the external tool and its version, as reported by it
configuration()        fingerprint of configuration affecting results
capabilities()         which requirement kinds it satisfies, for which scope
satisfy(request)       run, and return a provider run outcome with provenance
explain(result)        human-readable justification
```

`providerVersion()` and `toolchainIdentity()` are separate because they change
independently and each one invalidates reuse on its own (I8).

The Provider contract is described in terms of identities, capabilities and
results, without reference to any .NET type. The first implementations are
in-process C# adapters. Whether out-of-process providers are supported, and
over what transport, is open decision 5; nothing in the contract may assume
the answer.

### The adapter rule

```text
TARGET    an adapter should normally stay small, on the order of 100 lines,
          and be writable from the documented interface alone.

REQUIRED  no core policy, no evidence validity logic, and no semantics of an
          unrelated tool may live in an adapter.
```

The target is a smell detector, not a pass/fail criterion. A hundred and one
correct lines are fine; eighty lines containing validity logic are not.

### Generality is proven, not claimed

Generality is demonstrated by adapters for materially different tools (I12),
and later by a conformance run against foreign repositories. Until then it is
a hypothesis.

---

## 8. Fixed responsibilities

```text
StatusMan   observe and explain            read-only, never mutates
MrProper    normalize and report           never stages, never approves
IronMan     satisfy evidence requirements  never owns provider semantics
Doorman     verdict for one staged state   never forges IronMan evidence
```

There is exactly one implementation per role.

Formatter providers run in check mode only. Normalization is MrProper's
authority and is never triggered by a provider.

---

## 9. Solution layout

```text
src/Codelaxy.Contracts   records: Snapshot, Requirement, Evidence, Verdict
src/Codelaxy.Core        decisions: requirements, validity, reuse, verdicts
src/Codelaxy.Git         the Git process boundary and Snapshot construction
src/Codelaxy.Cli         entry points
tests/Codelaxy.Tests     xUnit
```

Dependency direction is one-way: `Contracts` ← `Core`, `Contracts` ← `Git`,
`Cli` on top.

`Core` consumes Snapshot contracts. It does not execute or parse Git.
`Codelaxy.Git` is the authoritative implementation that constructs repository
snapshots from Git. This is a separation of concerns, not an abstraction over
version control systems: no support for other systems is planned or designed
for.

Failures at the Git boundary are reported in that layer's own terms (I13) and
never translated into evidence states.

---

## 10. Lessons learned, written as prohibitions

Each line below is a mistake that already happened. Reintroducing one is a
regression, not a design choice.

1. Do not let Git inherit `GIT_DIR`, `GIT_WORK_TREE`, or `GIT_INDEX_FILE` from
   the caller.
2. Do not run Git or providers through a shell.
3. Do not correct Git's path answers with string manipulation.
4. Do not read or mutate the development repository's state from tests.
5. Do not let the tool's only consumer be the project it lives in.
6. Do not put build, link, or test-framework semantics anywhere in the core.
7. Do not run the expensive gate on every commit without a way to opt out.
8. Do not report success from missing information.
9. Do not mutate half a state and then discover the problem.
10. Do not claim a verification result that was not observed in output.
11. Do not merge while a check is failing.
12. Do not declare a generic interface stable after one consumer.
13. Do not execute repository-declared code without explicit trust.
14. Do not test only the happy path. Missing tools, spaces in paths, running
    outside a repository, poisoned environment, and detached HEAD are normal
    cases.
15. Do not build an abstraction for a second implementation nobody has asked
    for.
16. Do not express an infrastructure failure as a verification result.
17. Do not collapse adapter version and tool version into one identity.
18. Do not claim support for a language that has no adapter.
19. Do not let one requirement kind be satisfied as a side effect of another.
20. Do not leave a coverage cell unexplained; either an adapter owns it or a
    written `NOT_REQUIRED` policy does.
21. Do not treat a requirement kind as the identity of a concrete requirement.
22. Do not let untrusted repository policy contribute to a granted verdict.
23. Do not freeze the provider contract around .NET-specific transport.

---

## 11. Open decisions

```text
1  distribution model for end users
2  shell TEST support: bats as a provider, or an explicit NOT_REQUIRED policy
3  Windows / macOS / Linux support matrix for 1.0
4  configuration format and schema
5  out-of-process providers: supported or not, and over what transport
```

None of these block current work. All of them block the first release.

Settled since revision 3: the CPU Router unfreeze condition, which is now
stated in the CPU Router integration milestone in `roadmap.md`.

---

## 12. Definition of done for every pull request

1. The change serves one named milestone or defect.
2. New behavior has focused tests; fixed regressions have regression tests.
3. Non-happy-path cases are covered where they apply.
4. No change adds a language-specific assumption to the core.
5. No change expands the core into provider territory.
6. No claim about verification appears without observed output.
7. Nothing is merged while a check is failing.
