# Codelaxy — Roadmap

> Status: draft, revision 8 — not ratified
>
> Revision 7 remains the ratified roadmap until this draft is approved. Its
> text is preserved in Git at commit `7a1b6eb`.
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

## How this roadmap is organised

This file is the authority for the list of phases, their order, and their
status. Each phase has exactly one detailed record in `docs/adr/`, named after
its identifier (`docs/adr/P1.2.md`).

The phase record is the only place where the scope, the gate, and their
evidence are written down. This file does not repeat them.

Each phase record also shows a status in its header. If the two differ, the
status in this file is the authoritative one, and the difference is a defect
to be fixed.

`docs/Codelaxy-Roadmap.ods` and `docs/roadmap-view/` are derived views. They
are not independent sources. Both still describe the reference state at commit
`ab71863`, which is revision 7. They will be regenerated in a separate change
once revision 8 is merged into `main`.

### Rules for phase records

- A checkbox is ticked only for work that is merged into `main` and has
  evidence: a test name, a CI run, or a pull request.
- Work in progress is listed in the In Progress table of the phase record,
  with its branch and reason, never as a ticked checkbox.
- `0/0` in a counter means that nothing is defined, not that something was
  verified.
- `0/0` in the Gate counter does not mean that a phase has no binding
  condition. Where revision 7 states a condition in another form, the phase
  record carries it in Notes and its Gate section points to it (P1.10).
- A status ratified in revision 7 is kept as ratified. It may predate full
  evidence under the rules above: a phase recorded as `DONE` can show
  unticked items. Such a status is not evidence that those items are met.
  Each gap is recorded as a change request in the phase record, and the
  items stay unticked until evidence is recorded.
- From revision 8 on, a phase is set to `DONE` only when every item of its
  gate is ticked. An empty gate (`0/0`) decides nothing by itself. A phase
  with an empty gate is set to `DONE` only when every item of its scope is
  ticked and the binding condition its Gate section points to, if there is
  one, is met. Today this applies to P1.10 (three scope items and the
  unfreeze condition) and to P2.6 (six scope items). P0.0 to P0.4 and P1.0
  have an empty gate and an empty scope; their `DONE` is the status ratified
  in revision 7.
- Dependencies and Unlocks in a phase record give the previous and the next
  phase in the order of this file. Revision 7 states an order, not
  dependencies, and these fields claim nothing more.
- A phase record refers to architecture documents instead of repeating them.

### Allowed values

```text
Phase status            PLANNED / IN PROGRESS / DONE
Decision status         OPEN / DECIDED
Change request type     BUG / SCOPE / GATE / PLAN
Change request status   OPEN / ACCEPTED / REJECTED / DONE
```

### Identifiers

Identifiers carry the phase prefix and a three-digit number:

```text
P1.2-D-001     open decision
P1.2-CR-001    change request
P1.2-R-001     risk
```

---

## Phase status

| Phase | Name | Status | Record |
|-------|------|--------|--------|
| P0.0 | Product contract freeze | DONE | [P0.0](adr/P0.0.md) |
| P0.1 | Snapshot / Requirement / Evidence / Verdict / Provider vocabulary | DONE | [P0.1](adr/P0.1.md) |
| P0.2 | Single MrProper authority | DONE | [P0.2](adr/P0.2.md) |
| P0.3 | Canonical legacy launcher | DONE | [P0.3](adr/P0.3.md) |
| P0.4 | Architecture and docs sync, standalone C#/.NET decision | DONE | [P0.4](adr/P0.4.md) |
| P1.0 | Standalone repository + .NET solution | DONE | [P1.0](adr/P1.0.md) |
| P1.1 | Git process boundary | DONE | [P1.1](adr/P1.1.md) |
| P1.2 | Snapshot engine | IN PROGRESS | [P1.2](adr/P1.2.md) |
| P1.3 | Requirement / Evidence / Verdict engine | PLANNED | [P1.3](adr/P1.3.md) |
| P1.4 | Provider interface | PLANNED | [P1.4](adr/P1.4.md) |
| P1.5 | CMake/CTest provider, wired explicitly | PLANNED | [P1.5](adr/P1.5.md) |
| P1.6 | dotnet test provider, wired explicitly | PLANNED | [P1.6](adr/P1.6.md) |
| P1.7 | Interface ratification | PLANNED | [P1.7](adr/P1.7.md) |
| P1.8 | Configuration and project detection | PLANNED | [P1.8](adr/P1.8.md) |
| P1.9 | Trust model | PLANNED | [P1.9](adr/P1.9.md) |
| P1.10 | CPU Router integration — ROUTER UNFREEZES | PLANNED | [P1.10](adr/P1.10.md) |
| P2.0 | Evidence persistence and safe reuse | PLANNED | [P2.0](adr/P2.0.md) |
| P2.1 | C++ and C# completion providers | PLANNED | [P2.1](adr/P2.1.md) |
| P2.2 | Python provider: pytest, ruff | PLANNED | [P2.2](adr/P2.2.md) |
| P2.3 | Shell provider: shellcheck, shfmt | PLANNED | [P2.3](adr/P2.3.md) |
| P2.4 | Foreign-repository conformance suite | PLANNED | [P2.4](adr/P2.4.md) |
| P2.5 | CI, distribution, documentation | PLANNED | [P2.5](adr/P2.5.md) |
| P2.6 | 1.0 | PLANNED | [P2.6](adr/P2.6.md) |

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

## Working rules

- One logical change, one commit, explicit staging, no blind `git add .`, no
  `--no-verify`.
- No claim that tests passed until the output has been seen.
- Expensive proof is not repeated when nothing relevant changed — and the
  cheap checks never wait for the expensive ones (I11).
- A milestone is done when its exit criteria are demonstrably met, not when
  the code exists.

---

## Changes from revision 7

Structure only:

- the sections P1.1 to P2.6 moved to `docs/adr/`, one file per phase; their
  scope bullets and exit criteria keep their wording, apart from line breaks,
  the case of the first letter, and the final `;` or `.`, and the exit
  criteria are listed there under the heading Gate;
- where revision 7 had a list or a table instead of bullets, each row became
  one scope item (P2.1, P2.4); each P2.4 item carries the added prefix
  "Automated run against a real third-party repository:", taken from the
  introductory sentence of that list in revision 7;
- P0.0 to P0.4 and P1.0, which revision 7 listed in the status table only,
  each received a phase record that states this;
- the status list became a table with a link to each phase record; names and
  statuses are unchanged.

New in revision 8, not present in revision 7:

- the section "How this roadmap is organised", with the rules for phase
  records, the allowed values, and the identifiers;
- evidence and ticked checkboxes in `docs/adr/P1.1.md` and `docs/adr/P1.2.md`;
- open decisions, change requests, and risks in `docs/adr/P1.2.md`, and two
  change requests and one risk in `docs/adr/P1.1.md`;
- Dependencies, Unlocks, and References in every phase record; Dependencies
  and Unlocks give the roadmap order only.

Interpretations made in revision 8, which need approval as such:

- P1.1: the list "Non-happy-path coverage required" is counted as the eighth
  scope item, so the Scope counter includes that test coverage;
- P1.1: the phase stays `DONE` as ratified while one scope item and three
  gate criteria are unticked (Scope 7/8, Gate 3/6);
- P1.10: the unfreeze condition is carried in Notes, not as a gate item; the
  Gate section points to it. Under the rule on `DONE`, the three scope items
  and that condition decide when the phase is set to `DONE`; revision 7
  states the condition for the unfreeze only;
- P2.6: the six unlabelled lines of revision 7 are placed under Scope, not
  under Gate (approved by the maintainer on 2026-11-12 in a comment on pull
  request #20). This decides how the phase record counts what blocks 1.0:
  the gate is empty, so under the rule on `DONE` the six scope items decide.

The wording of every scope bullet and exit criterion of revision 7 is kept,
apart from the normalisation named above. The interpretations above change
how some of them are classified and counted.
