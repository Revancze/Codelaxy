# Codelaxy

**Git-native evidence for exact repository states.**

Codelaxy is a verification evidence engine that answers one question:

> What has already been proven for this exact repository state, by which
> authority, and is that proof still valid?

Instead of treating every build, test, lint, or format check as something that
must always be executed again, Codelaxy models verification as evidence bound
to an exact repository state.

```text
Snapshot
   │
   ▼
Requirements
   │
   ├── valid evidence exists ─────► REUSE
   │
   └── proof is missing/invalid ──► Provider
                                      │
                                      ▼
                                   Evidence
                                      │
                                      ▼
                                    Verdict
```

> **Development status:** pre-1.0 and under active development.
>
> The architecture and data model are being built before the public CLI.
> Codelaxy is not yet ready for end-user installation or production use.
> See the [roadmap](docs/roadmap.md) for authoritative milestone status.

## Why Codelaxy?

Traditional verification pipelines often answer:

> Which commands should I run?

Codelaxy asks a different question:

> Which claims must be proven, what proof already exists, and is that proof
> valid for the repository state being judged now?

This distinction is fundamental.

Codelaxy does not own compiler commands, test-framework semantics, formatting
rules, or build recipes. Those belong to providers. Codelaxy owns the model
that decides which proof is required, whether existing proof may be reused,
and whether the resulting repository state receives a successful verdict.

## Core model

| Concept | Meaning |
|---|---|
| **Snapshot** | The exact repository state being judged |
| **Requirement** | What must be proven, never how |
| **Evidence** | An immutable verification record bound to identity |
| **Verdict** | The decision for one exact Snapshot |
| **Provider** | The component that produces fresh Evidence |

The vocabulary is intentionally small. These names form part of the
architecture contract.

## Git-native by design

Git is infrastructure, not a provider.

Repository identity and state are obtained from Git itself rather than
reconstructed through filesystem guesses or path rewriting.

The Git boundary is designed around several rules:

```text
Git is authoritative for Git state
Git is invoked directly, without a shell
inherited repository-redirecting Git environment is isolated
timestamps are never treated as identity
uncertainty never silently becomes success
infrastructure failure is not verification evidence
```

The complete set of architectural invariants is documented in
[docs/architecture.md](docs/architecture.md).

## What Codelaxy is not

Codelaxy is deliberately **not**:

```text
a build system
a task runner
a test framework
a formatter
a linter
a dependency resolver
a replacement for Git
a CI platform
```

Those tools remain responsible for their own domains.

Codelaxy determines what proof is required and whether that proof is valid.

## Architecture

```text
Codelaxy
├── src/
│   ├── Codelaxy.Contracts/
│   │   └── shared Snapshot, Requirement, Evidence and Verdict contracts
│   │
│   ├── Codelaxy.Core/
│   │   └── verification policy, evidence validity, reuse and verdict logic
│   │
│   ├── Codelaxy.Git/
│   │   └── Git process boundary and Snapshot construction
│   │
│   └── Codelaxy.Cli/
│       └── future public command-line interface
│
├── tests/
│   ├── Codelaxy.Tests/
│   │   └── xUnit test suite and invariant tests
│   │
│   └── Codelaxy.ProcessTestHelper/
│       └── helper executable for process-boundary tests
│
└── docs/
    ├── architecture.md
    └── roadmap.md
```

Dependency direction is intentionally constrained.

```text
Contracts  ◄── Core
    ▲
    └──────── Git

Contracts + Core + Git
          ▲
          │
         CLI
```

The Core does not execute Git and does not contain language-specific build,
test, lint, or format semantics.

## Development status

The project is being implemented milestone by milestone.

| Area | Status |
|---|---|
| Standalone .NET solution | Implemented |
| Git process boundary | Implemented |
| Snapshot engine | In progress |
| Requirement / Evidence / Verdict engine | Planned |
| Provider interface | Planned |
| CMake / CTest provider | Planned |
| .NET test provider | Planned |
| Repository configuration | Planned |
| Worktree trust model | Planned |
| Evidence persistence and reuse | Planned |
| Public installation/distribution | Planned |
| 1.0 | Planned |

The detailed sequence, exit criteria, and integration milestones live in the
[roadmap](docs/roadmap.md).

## Snapshot work

Snapshot identity is intended to describe the repository state that is actually
being judged, not incidental filesystem metadata.

Current Snapshot development covers Git-owned state including HEAD, index,
staged state, working-tree state, unmerged index entries, repository object
format, and executable-bit semantics.

The design is deterministic: equivalent repository states must produce
equivalent identities regardless of incidental timestamps or enumeration
order.

## Planned public CLI

The intended public command surface is deliberately small:

```text
codelaxy status
codelaxy init
codelaxy verify
codelaxy explain
codelaxy verdict
```

These commands describe the planned public contract.

**They are not all implemented yet.**

The current CLI project is still a development scaffold while the underlying
Snapshot, Evidence, Provider, and Verdict contracts are established.

## Requirements

Development currently requires:

```text
Git
.NET 10 SDK
```

The repository pins the .NET SDK feature band through `global.json`.

At the current revision the baseline SDK is:

```text
10.0.101
```

with `latestPatch` roll-forward enabled.

## Build

Clone the repository and build the solution:

```bash
git clone git@github.com:Revancze/Codelaxy.git
cd Codelaxy
dotnet build
```

Run the complete test suite with:

```bash
dotnet test
```

No repository-wide clean should normally be necessary when switching between
Windows and Linux/WSL development.

Build artifacts are isolated by host:

```text
Windows     bin/windows/...
Linux/WSL   bin/linux/...

Windows     obj/windows/...
Linux/WSL   obj/linux/...
```

This allows the same checkout to be built from Windows and WSL without sharing
generated MSBuild state.

Development is currently exercised on Windows and Linux/WSL. This does not yet
constitute the final 1.0 platform support matrix.

## Verification philosophy

Codelaxy follows a conservative rule:

```text
valid proof exists            REUSE
validity cannot be proven     VERIFY AGAIN
verification fails            NO SUCCESSFUL VERDICT
```

Unknown, stale, malformed, incomplete, corrupt, conflicting, or unverifiable
evidence can never silently satisfy a requirement.

A successful verdict therefore means that every applicable requirement has
either valid passing evidence or an explicit policy stating that the
requirement is not applicable.

## Providers

Providers are responsible for obtaining fresh evidence.

The Core must not know whether that evidence came from CMake, CTest,
`dotnet test`, pytest, shellcheck, clang-format, or another tool.

A provider reports its capabilities and the identities needed to make its
evidence reproducible:

```text
requirement identity
provider identity and version
provider configuration fingerprint
toolchain identity
snapshot identity
evidence schema version
```

Changing an identity that affects verification invalidates evidence reuse.

The provider contract remains provisional until it has been exercised by
materially different consumers.

## Trust

Repository configuration may eventually select providers and requirements.
That also means repository configuration can cause code chosen by a repository
author to execute.

For that reason, repository-declared execution is intentionally blocked by the
architecture until explicit worktree trust semantics exist.

Trust is a first-class design requirement, not a feature to be added after the
execution model.

## Documentation

The two authoritative design documents are:

- [Architecture contract](docs/architecture.md) — invariants, vocabulary,
  responsibility boundaries, result model, and design constraints.
- [Roadmap](docs/roadmap.md) — implementation milestones, exit criteria, and
  the path to 1.0.

When this README and the architecture documentation disagree, the architecture
contract wins.

## Development discipline

Changes are expected to preserve the architectural invariants and remain
evidence-driven.

The repository follows a strict development workflow:

```text
one logical change → one commit
explicit staging
no blind git add .
no --no-verify
focused regression tests for defects
no claim of success without observed output
no merge while required checks are failing
```

A milestone is complete only when its exit criteria are demonstrably met.

## Project direction

The first major integration target is CPU Router.

Codelaxy will be considered capable of unlocking that project when an external
Codelaxy instance can produce a valid Verdict for an exact staged CPU Router
Snapshot through the CMake/CTest provider.

Beyond the 1.0 verification model, future work may include finer-grained
dependency and impact analysis. Those capabilities are intentionally outside
the current core contract.

---

Codelaxy is being built around a simple principle:

> **Proof belongs to an exact state. If Codelaxy cannot prove that existing
> evidence still applies, it verifies again.**
