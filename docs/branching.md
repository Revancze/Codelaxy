# Codelaxy — Branching & Verification Policy v1

> Status: **DRAFT, decisions D1–D12 taken, awaiting independent review of the
> final wording.** Not ratified. Not part of any approved document; nothing
> here has been written into the Git code of conduct or into `docs/`.
>
> Once approved, the policy lives **exclusively** in `docs/branching.md` as the
> single binding source (D5). Until then this file is a proposal.
>
> Decision it implements: the user's working architectural choice of 2026-10-21,
> "namespaces, not permanent branches" (agreed in discussion by the user, GPT
> and Claude). Decisions D1–D12 were taken by the user on 2026-10-21 and are
> recorded in §10.
>
> Evidence snapshot: `origin/main` = `f193c0a` (merge of PR #11), 2026-10-21;
> re-checked on `2c05dd8` (merge of PR #12): the CI workflow,
> `docs/architecture.md` and `docs/roadmap.md` are unchanged between the two, and
> only `docs/snapshot-test-matrix.md` differs (W Golden now recorded as covered).
> Statements marked **OBSERVED** were checked against that commit or the live
> GitHub repository on that date; **UNKNOWN** means they could not be
> confirmed; **GAP** marks a place where the policy states more than is
> enforced. None is tagged GAP now; the rows of the §5 table marked "convention
> only" are the places where the policy rests on convention, and no claim is
> made that every requirement is technically enforced.
>
> Language: English, to match `docs/`. The discussion that led here was Czech.

## 1. Principles

1. **`main` is the only permanently existing branch.** Every other development
   level is a *namespace* (a naming prefix with rules), not a branch that has
   to exist. Integration branches exist only while there is a real need (§4).
2. **Every namespace has a stated meaning of trust** (§3).
3. **Acceptance into `main` is common to all namespaces** (§5). A branch cannot
   skip CI or review because it was born in a less strict namespace. The
   namespaces differ in what is allowed *before* acceptance, not in what is
   required *for* acceptance.
4. **Evidence decides, the prefix only classifies.** A green build, passing
   tests, a review, and the binding of each to a named identity (§5, §6) matter more
   than any branch name.
5. **Evidence is proportional to risk, not to the branch name.** A prose fix
   and a change to `GitSnapshotBuilder` do not need the same proof (§6). Tests
   must prove a named requirement or invariant and never exist just to satisfy a
   prefix. Snapshot tests map to the Test Matrix
   (`docs/snapshot-test-matrix.md`).
6. **Unknown impact is decided conservatively.** Evidence whose validity cannot
   be defended is not reused; it is never reused optimistically (§6).

Why not permanent integration branches per level: every long-lived parallel
branch is another history to keep in sync (back-merges, cherry-picks, "which
branch is the truth"). The project has no release consumers and no parallel
supported versions that would pay for that cost. **OBSERVED:** PRs #6–#11 all
went through short-lived branches into `main`; the one integration branch,
`dev/codelaxy/p12-foundation`, was temporary and is already merged.

## 2. Naming

```text
<level>/<short-description>
<level>/<agent-or-area>/<short-description>
rc/v<MAJOR>.<MINOR>.<PATCH>
```

Both forms have the same namespace meaning. Include a roadmap ID in the short description when the work maps to a roadmap item; exploratory work need not invent one. Integration names follow §4. Examples (illustrative): `exp/claude/git-history-probe`,
`dev/codex/f1-stdin-paths`, `fix/p12-windows-git-path`,
`test/m1-worktree-golden-001`, `docs/p12-roadmap-workbook`, `rc/v0.2.0`.

**Reserved names (Git ref hierarchy).** Git cannot hold both `refs/heads/dev`
and `refs/heads/dev/x`. Verified on 2026-10-21:

```text
$ git branch alpha main && git branch alpha/snapshot-v2 main
fatal: cannot lock ref 'refs/heads/alpha/snapshot-v2': 'refs/heads/alpha' exists
```

Therefore **no branch may be named exactly** `exp`, `alpha`, `dev`, `rc`,
`feat`, `fix`, `test`, `docs`, `archive`. Namespaces are only ever prefixes.
The same applies one level down: do not create both `dev/claude` and
`dev/claude/x`.

**Legacy names.** **HISTORICALLY OBSERVED** on the remote: `feature/git-process-boundary`
(`feature/` is not a defined namespace; `feat/` is). It is not renamed
retroactively; new branches follow this section. (`fix/windows-git-path-alias`
conforms to the short form and is no longer a legacy case.)

## 3. Namespaces and what they mean

| Prefix | Meaning of trust | May fail / be abandoned | Reaches `main` how |
|---|---|---|---|
| `exp/*` | Experiment, hypothesis, probe. **No promise of correctness.** Mutation/security experiments live here. | Yes. Ending without merge is a normal outcome. | Promotion, §3.1 |
| `alpha/*` | Verified prototype with a **written contract** (§3.2). | Yes, until accepted | Pull request, §5 |
| `dev/*`, `feat/*`, `fix/*` | Controlled development of intended product change. `feat/` and `fix/` are the same level as `dev/`. | Rarely | Pull request, §5 |
| `test/*` | Tests, fixtures, Golden references. The change adds or alters proof, not behaviour. | Rarely | Pull request, §5 |
| `docs/*` | Documentation only. | Rarely | Pull request, §5 |
| `rc/vX.Y.Z` | **Temporary** release preparation. Only fixes for defects found during acceptance. Exists only between cutting the candidate and tagging it. | n/a | Pull request, §5, then deleted |
| `main` | Stable, accepted state **with recorded evidence**. | n/a | n/a |

Two clarifications that are easy to get wrong:

- **`main` stable does not mean releasable.** A milestone can be accepted and
  stable on `main` and still not meet the bar for a public release. Release
  readiness is decided separately (§7).
- **The prefix proves nothing.** `dev/` does not mean tested and `exp/` does
  not mean unsafe; what was actually run and reviewed does (§6).

### 3.1 Promotion from `exp/*` to `main` (D2)

- **Default path:** promote the idea to a **clean working branch created from
  the current `main`** (`dev/*`, `fix/*` or `test/*`). Take the solution
  selectively, write targeted tests, and keep a **reference to the originating
  experiment** (branch or `archive/` tag) in the PR description.
- **Direct PR from `exp/*` is allowed only** when the branch has a **clean,
  auditable history** and then meets **all the same** requirements for diff,
  review, CI and evidence as any other change into `main`. "Clean auditable
  history" (D10) means: an **understandable diff**, a **traceable origin** of
  the changes, **experimental interventions resolved**, and the **required
  gates met**. It does **not** mean that every historical experimental commit
  passed all tests on its own. An experiment too tangled to meet this is
  converted to a clean working branch (the default path above).
- **The `exp/*` prefix bypasses no gate.**
- **Cherry-picking or rewriting does not carry the validity of old evidence
  with it.** Evidence is re-established on the new commit (§6).
- **A classic merge commit is the merge method** (§5); it is the only one enabled
  in the repository settings.

### 3.2 `alpha/*` (D1)

`alpha/*` is a verified prototype with a **written contract**: the named
requirements or invariants it claims and the evidence it intends to provide,
written down in the branch or PR before the work is judged. Snapshot work maps
to applicable Test Matrix cells; other work names its relevant contract or
architectural invariant. It has targeted tests.

What differs from `dev/*` is the work **before** acceptance: the contracted
evidence may still be incomplete while a branch is in `alpha/*`. Acceptance
is identical: before reaching `main`, the required evidence for the change,
including applicable snapshot Test Matrix coverage, and every requirement of
§5 and §6 must hold.

CHECK (not a decision): after the first few `alpha/*` branches, confirm that
the namespace changed a real decision. If it did not, retire it.

## 4. Integration branches

This section is part of the policy upon ratification, under the same draft status as the rest of this document. Integration branches are allowed only when a real need exists, never by default:

- named `<level>/integration-<topic>` (never plain `dev/integration`, which
  would block `dev/integration/…`);
- written justification, an owner, and an exit condition recorded where the
  branch is created (PR description or tracking issue);
- exactly the scope its justification states. **OBSERVED** in `docs/roadmap.md`
  (P1.10): "exactly one dedicated integration branch of CPU Router is
  permitted", and non-integration commits on it are "a violation of the
  freeze, not a grey area". That stays as is; this section only generalises
  the discipline;
- deleted after its exit condition is met.

## 5. Acceptance into `main` (common to every namespace)

**What GitHub enforces today (OBSERVED, `gh api`, 2026-10-21).** Repository
`Revancze/Codelaxy`, public. Ruleset "Protect main" (id 24467006), enforcement
`active`, applies to the default branch, **no bypass actors**:

- deleting `main` is blocked; non-fast-forward updates (force-push) are blocked;
- changes must go through a pull request; **required approving reviews: 0**;
  review-thread resolution is required; the ruleset's own list of allowed merge
  methods names merge, squash and rebase (it does not restrict them further);
- required status checks: `windows-latest` and `ubuntu-24.04`, and the branch
  must be up to date with `main` (strict policy).

**GitHub repository settings (a separate layer from the ruleset).**
**OBSERVED**, `gh api repos/Revancze/Codelaxy`, 2026-10-21:
`allow_merge_commit = true`, `allow_squash_merge = false`,
`allow_rebase_merge = false`; also `allow_auto_merge = false` and
`delete_branch_on_merge = false`. A merge method must be allowed by **both**
layers, so the effective result is that **only a merge commit can be used**,
even though the ruleset's list still names all three. The restriction lives in
repository settings, not in the ruleset; a repository administrator can change
it, so it is enforced by configuration, not locked against its owner.

**What CI runs** (**OBSERVED**, `.github/workflows/ci.yml`): on pushes to `main`
and on **every pull request whatever its base**, on `windows-latest` and
`ubuntu-24.04`: `dotnet csharpier check .`, the warning-gate self-tests, the F3
warning gate, `dotnet test`, and the Golden Git configuration isolation check.
Those steps live in one job per OS, so the two required checks cover all of
them.

**Which commit is meant: three identities (OBSERVED).** The workflow triggers
on `pull_request` and its `actions/checkout` step has no explicit `ref`, so
GitHub checks out a **temporary test merge** of the PR head and the target
branch, not the PR head itself. Evidence, run 39633138383 (PR #12):
`git checkout --progress --force refs/remotes/pull/12/merge`, then
`HEAD is now at ad2be61 Merge c280e938… into f193c0ac…`, where `c280e938` is
the PR head. The policy therefore distinguishes:

1. **PR head** — the change being accepted. The auditor assesses it and the
   maintainer accepts it.
2. **CI test merge commit** — the combined state CI actually verified (PR head
   merged into the then-current target branch). Useful for integration testing,
   and correct as it is; the workflow is **not** changed by this policy.
3. **Final merge commit** — created by GitHub on `main` at merge time, a third
   identity, recorded after the merge.

Records name the identity they refer to. An audit or review refers to the PR
head; CI evidence refers to the test merge commit and states which PR head it
combined; the final merge commit is noted after the merge. Because the
required checks use the strict policy, the PR head branch must be up to date with the target branch,
which keeps the tested combination current. CI records also name the target/base commit used to construct the test merge.

**Policy (D4).** `main` is protected by the GitHub ruleset. A change is
accepted into `main` only when all of the following hold for the **PR head
being merged**:

1. A pull request exists and the enforced checks are green (on the CI test
   merge of that head, see the identities above).
2. Review has been done **in proportion to the change's risk** (§6) and is
   recorded in the PR. A formal GitHub approval is **not yet mandatory**, but
   **the absence of an independent review must be stated**, not left silent.
   Who plays which role: §5.1 (D6).
3. The evidence required by the change's risk class (§6) is recorded and tied
   to the applicable identity defined above, with its relationship to the accepted PR head recorded.
4. Working rules from `docs/roadmap.md` hold: one logical change per commit,
   explicit staging (no blind `git add .`), no `--no-verify`, no claim that
   tests passed without having seen the output.
5. **A classic merge commit is the only permitted merge method.** It is
   enforced today by the repository settings (see above), not by the ruleset.
   Neither layer is changed by this policy.

**Enforced versus convention, stated plainly:**

| Rule | Enforced by | Convention only |
|---|---|---|
| PR required, no direct push or deletion of `main` | ruleset | |
| Both OS checks green, branch up to date | ruleset | |
| Review threads resolved | ruleset | |
| Merge commit as the only method | repository settings | |
| Review in proportion to risk, absence declared | | yes |
| Evidence tied to a named identity (PR head, test merge) | | yes |
| Merged branches deleted | | yes (`delete_branch_on_merge = false`) |

### 5.1 Roles in a review (D6)

Three **roles**, which are not the same thing as three persons:

1. **Author** — the human or agent who produced the change.
2. **Independent auditor** — ideally **a different agent** (or a separate
   session) that did not write the change. It examines the diff, the tests, the
   invariants they claim to prove, and the evidence. It independently verifies
   the underlying records and their applicability rather than trusting the
   author's summary, using the evidence-assessment rules below. If the auditor
   is the same model as the author, the PR says so.
3. **Maintainer** — the user. Decides whether to accept the change and
   authorises the merge. Recorded in the PR as the user's acceptance.

**Roles are not persons.** The author and the maintainer may be the same human;
for a sole maintainer that is the normal case. The rule is about the auditor:
when an audit is mandatory (R3, R4), the auditor must not be assessing their own
work, so the author and the auditor are never the same person, agent or
session. For R0 and R1, where an audit is optional, the auditor role may stay
unfilled, and the PR says so (§5, item 2). An agent never accepts its own
work, so an agent can be an author or an auditor but never the maintainer.

An AI audit is **not** a formal GitHub approval and **not** an automatic PASS,
and it is not a guarantee of correctness. It is an additional, documented check
that supports the maintainer's decision and never replaces it. An agent never
accepts its own work. The single human maintainer remains the final authority
for approving a merge, and that decision is recorded in the PR.

**The audit must be traceable.** The audit record, kept in or linked from the
PR, states:

1. the **PR head** that was audited (full commit id);
2. the **scope** of the check — what was examined and what was not;
3. the **relevant evidence** it relied on, and which of it the auditor inspected, re-ran or reused, and why;
4. the **findings**, each with the evidence for it;
5. the **unverified areas**, named explicitly.

**Later commits and delta audit (D9).** An audit of an earlier commit does not
automatically cover later changes, but a full repeat is not always needed. A
**targeted delta audit** may cover what changed since, and **reuse the evidence
whose validity the later changes did not affect**, under the conservative rule
of §6: evidence that depends on what changed, or whose dependency cannot be
determined, is re-established. The **final audit conclusion must refer to the
current PR head**, the commit actually being merged, and must say which earlier
results were reused and why.

**A changed target branch also requires reassessment.** If the target/base
commit changes while the PR head stays unchanged, record the old and new base
and test merge identities. The auditor (when an audit is required or performed)
assesses whether the changed base affects the reviewed integration, assumptions
or evidence. Reuse requires a documented justification of independence; affected
or indeterminate conclusions and evidence are re-established by a delta audit.
Required CI checks must pass on the current test merge. An unchanged PR head
alone does not preserve an audit of the earlier integrated state.

**How the auditor assesses evidence.** Mandatory audits for R3/R4 remain
mandatory; the following distinguishes inspection from execution:

- **Existing CI evidence:** inspect the actual run, job results and relevant
  logs, bind them to the PR head, base and test merge, and check scope, platform
  and toolchain applicability. This can establish Linux execution evidence;
  a green badge or the author's summary alone cannot. A duplicate local run of
  the whole CI suite is not required merely because an audit is taking place.
- **Targeted reruns:** the auditor independently executes or initiates the
  relevant Golden/invariant or negative checks for newly affected invariants,
  changed references or changed gates, and inspects their output. Executing
  these checks in CI under the auditor's assessment is permitted. Required
  mutation and negative-gate evidence is retained; this rule does not waive it.
- **Delta reuse:** previously independently assessed results may be reused only
  when the auditor documents why subsequent changes, including base changes,
  cannot affect their validity. Affected or indeterminate proof obligations
  require fresh verification. Record what was inspected, rerun or reused and
  why; required CI still passes on the current test merge.

**Depth follows the risk class (§6).** The higher the class, the more thorough
the independent assessment. Which classes require an independent audit:

| Class | Independent audit |
|---|---|
| R0 | optional |
| R1 | optional |
| R2 | recommended |
| R3 | **required** — independent assessment of Golden/invariant evidence, targeted reruns for affected invariants, and verified Linux execution evidence, under the assessment rules above |
| R4 | **required** — includes the impact assessment of §6 reviewed by the auditor |

(Decided by the user on 2026-10-21. How a class is determined: §6.1.)

**If an audit is missing.**

- For **R2** (recommended) the absence is stated in the PR; the maintainer may
  still accept.
- For **R3 and R4** (required) the absence is stated explicitly and **the merge
  cannot be approved**. A missing required audit **cannot be replaced by merely
  accepting the risk.** Any exception needs a **separately approved procedure**,
  recorded in the PR before the merge. Re-classifying the change is only
  allowed under §6.1 rule 4.
- Silence is never a valid state.

**The maintainer's authority has a limit.** The maintainer is the final
authority for approving a merge, but may not bypass the checks and protection
rules GitHub enforces on `main` (§5). Nothing in this section lets a change
skip them.

**Operations needing separate approval.** Commit, push, opening a PR and merge
are each a separately approved operation. An agent works in `exp/<agent>/…` in
its sandbox, does not push, and does not merge. Moving work up a level needs
the user's explicit approval. (Source: standing instruction of 2026-10-12, not
yet in any repository document.)

## 6. Evidence proportional to risk

The classes below are the agreed starting set (D3) and are refined as real PRs
show what is missing. The **"Typically touches"** column describes what usually
falls into a class; **it does not decide the class.** The class follows the
actual impact of the change (§6.1).

| Class | Typically touches | Minimum evidence |
|---|---|---|
| R0 | Prose, comments, docs without claims about behaviour | CI green; review of factual accuracy. No new tests required. |
| R1 | Cosmetic changes to tests, fixtures or Golden files that do not affect what a test asserts or how it behaves (formatting, renames, comments) | CI green on both operating systems; the review confirms from the diff that the change has no behavioural effect. |
| R2 | Production code outside the identity path; **a new, isolated, independent Golden test** | Tests for the changed behaviour; F3 warning gate shows no regression; both OS in CI. For a new Golden test: it proves a named Test Matrix invariant; its reference is computed independently of Codelaxy output and never rewritten to match it; mutation check where meaningful; run on **both** Windows and Linux, and a platform difference is explained, not hidden. |
| R3 | Snapshot identity path: `GitSnapshotBuilder`, index canonicalisation, fingerprint domains and `SchemaVersion`; a change of meaning or expected values of an **existing** Golden reference; a shared fixture such as `GoldenGitFixture` where it affects the trustworthiness of tests | Applicable verification requirements from R1 and R2 (both OS checks, factual review and tests for the affected behaviour; R1's cosmetic/no-behavioural-effect condition does not apply), plus: Test Matrix reviewed for applicability in every R3 PR and updated in that PR only if relevant invariants, coverage or evidence status change (otherwise record why no update is needed), an independent Golden or invariant test for the changed path, mutation evidence, a Linux run (not Windows only), and an explicit note on whether any fingerprint domain/version changes. |
| R4 | **High potential impact on evidence and on the things evidence depends on**: CI and workflow files, the mechanism that decides the trustworthiness of evidence across the project (for example the warning gate and the Golden isolation check), tooling, security boundaries (`GitProcessRunner`, executable resolution), and **inputs shared by all builds** — `global.json`, `packages.lock.json`, `Directory.Build.props`, `.globalconfig`, `.editorconfig`, `CodeMetricsConfig.txt`, `BannedSymbols.txt` | A written **impact assessment**: which existing evidence depends on the changed input. See the R4 rule below. A short threat/rollback note for CI and security boundaries. Proof that a changed gate still fails when it should. |

**R4 rule (D3).** R4 expresses *potential impact*, not an instruction to run
everything. A change to, say, `Directory.Build.props` means the evidence that
depends on that setting is **re-judged conservatively**:

- evidence that depends on the changed input, or whose dependency cannot be
  determined, is treated as **not valid** and re-established;
- evidence that is demonstrably independent of the changed input may be kept,
  with the assessment recorded;
- there is **no automatic blanket invalidation** of all existing evidence and
  **no mandatory full rebuild**;
- **unknown impact leads to the conservative decision**, never to an optimistic
  reuse. This is the same principle Codelaxy itself follows: do not repeat work
  needlessly, never recycle evidence whose validity cannot be defended.

### 6.1 How a class is determined (D7, D8)

1. **The class follows the real impact of the change**, in particular the
   possibility of a **false PASS** or an **incorrect REUSE**, and the effect on
   invariants and evidence. The type of file alone does not decide it.
2. **Golden references and test infrastructure can fall into a higher class**
   when they affect the trustworthiness of evidence.
3. **For R3 and R4 a missing required audit cannot be replaced by accepting the
   risk** (§5.1). An exception needs a separately approved procedure.
4. **Moving a change to a lower class must be justified by an actual reduction
   of scope or risk**, shown in the PR (for example by splitting the change),
   never by the wish to avoid a mandatory audit or the CI.
5. **The maintainer remains the final authority for approving a merge, but may
   not bypass the checks GitHub enforces** (§5).

**Default classification for Golden and test changes (D8).** These are
starting points, not absolutes:

| Change | Default class |
|---|---|
| Cosmetic change without effect on how the test behaves | R1 |
| New, isolated, independent Golden test | R2 |
| Change of meaning or expected values of an existing Golden reference; change of a shared fixture that affects the trustworthiness of tests | R3 |
| Change of a mechanism that decides the trustworthiness of evidence across the project | R4 |

Using an existing shared fixture unchanged does not by itself make a change R3;
changing it in a way that affects the trustworthiness of tests does. The actual
impact may raise **or lower** the default, **if that is documented**
in the PR. The defaults are consistent with the definitions in §6.

**Who decides the class (D8).**

1. The **author** proposes the class, with a justification.
2. The **auditor** verifies it when an audit is mandatory or has been done.
3. The **maintainer** approves the final class and decides on the merge.
4. When doubt remains, the **higher credible class applies until the opposite
   is shown.**
5. A lower class must never serve to avoid a mandatory audit or the CI.

**Recording.** The classification, with its justification, and any later
re-classification are recorded in the PR. What matters is the real effect on
invariants, on evidence and on the risk of a false PASS or an incorrect REUSE,
not the label.

**A class is not a fixed property of a PR.** If, while the PR is open, a change
is added to production code, to a shared fixture, or to CI, the class may
change. The class is then reassessed, and the required evidence and audits are
reassessed with it. An audit of an earlier head does not automatically cover
the commits added afterwards; see the delta audit in §5.1.

Rules that apply to every class:

- **Evidence is bound to an identity.** A review record names: the PR head
  (commit and tree id); for CI evidence, the test merge commit and the PR head
  it combined (§5); the command, the platform and tool versions, the result in
  numbers, and the date. A rebase, force-push, cherry-pick or rewrite
  invalidates its attribution to the new PR head; it does not transfer automatically. CI must run for the current test merge. Other results may be carried into a new audit record only under the documented, conservative delta-audit rules of §5.1; otherwise re-run them.
- **The identity of a PR record is narrower than the identity Codelaxy's own
  evidence needs, and the two are never presented as one.** Binding a review or
  CI result to a commit identifies *what was examined in the development
  process*. Evidence that Codelaxy itself produces is bound by the ratified
  invariant **I8** (`docs/architecture.md`) to much more: the snapshot
  (including SchemaVersion and the H, I, S and W fingerprints), the relevant inputs, the exact requirement kind and identity, the evidence schema version, the
  provider identity and version, the provider configuration fingerprint, and
  the toolchain identity. When a PR cites evidence produced by Codelaxy, it
  cites that full identity. When evidence concerns a working-tree state rather
  than a clean checkout of a commit, a commit id does not identify it and the
  W fingerprint belongs to the identity.
- **Cheap checks never wait for expensive ones** and expensive proof is not
  repeated when nothing relevant changed (`docs/roadmap.md`, invariant I11).
- **Unverified is stated as unverified.** "Not run on Linux", "not checked in
  CI yet" go in the PR text, not into silence.
- A test exists to prove a named requirement or invariant. Snapshot tests map to the applicable Test Matrix cells. Provider, CI, tooling and security tests name the applicable contract, gate requirement or architectural invariant instead; they need not occupy a snapshot Test Matrix cell. A green test without an identified proof obligation does not count as evidence for any class above R0.

## 7. Releases and tags

- **Completing a roadmap milestone does not create a release tag.** A tag is
  created by a deliberate release decision, not as a side effect of DONE.
- Product versions use SemVer tags: `vX.Y.Z`, `vX.Y.Z-alpha.N`,
  `vX.Y.Z-rc.N`. A tag names a commit; it is not a branch.
- `rc/vX.Y.Z` is cut when a release is prepared and deleted once tagged and
  merged. It is never a standing branch.
- Retired experiments worth keeping are tagged `archive/<agent>/<name>` and the
  branch is deleted. (Current agent practice; formalised here.)

## 8. Lifecycle and cleanup

- A temporary branch is deleted after its merge (locally and, if the owner
  agrees, on the remote). Nothing is deleted automatically.
- Only `main` is exempt from cleanup by age. All other branches are
  candidates.
- Age thresholds are advisory: a branch with no activity for 60 days gets a
  *decision* (finish, archive by tag, or delete), not an automatic removal.
  `gitradar.sh` uses 14 days (active) and 60 days (stale) as tool defaults;
  those defaults are not policy.

## 9. What this draft deliberately does not do

- Does not create or delete any branch, tag or rule on GitHub, and does not
  change the existing ruleset or the repository settings (D12).
- Does not require tests *because of a prefix*; tests follow risk and the
  named requirement or invariant (the Test Matrix for snapshot tests).
- Does not change `docs/roadmap.md`, the roadmap workbook, `MICROMAP.md` or
  `LONGTERMMAP.md`. A conflict with the ratified roadmap or the binding
  architecture needs its own approval (D5).
- Does not rename legacy branches.
- Does not change `gitradar.sh`, which keeps working with this model
  (decision of 2026-10-21).
- Does not put policy text into the Git code of conduct or agent instructions;
  those link to `docs/branching.md` and do not duplicate it (D5).

## 10. Decisions taken (2026-10-21, by the user)

| ID | Question | Decision |
|---|---|---|
| D1 | What is `alpha/*`? | A verified prototype with a written contract (§3.2). Differs from `dev/*` only in what is required before acceptance; acceptance is identical. Re-check after a few uses. |
| D2 | How does work from `exp/*` reach `main`? | Default: promotion to a clean branch from current `main`, with selective adoption, targeted tests and a reference to the origin. Direct PR only with clean auditable history and identical requirements. `exp/*` bypasses nothing; cherry-pick/rewrite does not carry evidence; a classic merge commit is the merge method (§3.1, §5). |
| D3 | Are R0–R4 right as a starting set? | Yes, with build/dependency inputs in R4; the class follows real impact, not file type (§6.1). R4 means high potential impact on evidence, not a mandatory full rebuild; unknown impact is decided conservatively (§6). |
| D4 | Enforcement? | The existing GitHub ruleset stays. Review is proportional to risk; formal approval is not yet mandatory but the absence of an independent review is declared. Merge commit as the only method is already enforced by the repository settings (not by the ruleset). Commit, push, PR and merge remain separately approved (§5). |
| D5 | Where does it live? | Exclusively in `docs/branching.md` once approved. The Git code of conduct and agent instructions only link to it. Roadmap and binding architecture stay untouched. |
| D6 | Second reviewer when the author is the only maintainer? | Three roles (§5.1): author; independent auditor, ideally a different agent, who independently assesses the evidence and performs targeted reruns under §5.1; maintainer (the user), who accepts and authorises the merge. The audit is supporting evidence, not a GitHub approval and not an automatic PASS; it must name the audited commit, scope, evidence, findings and unverified areas, and its depth follows the risk class. A missing required audit is declared; for R3/R4 it blocks approval and cannot be replaced by accepting the risk (§5.1). An agent never accepts its own work. |
| D7 | Which classes require an independent audit? | R0, R1 optional; R2 recommended; R3, R4 required. Class follows real impact (false PASS, incorrect REUSE), not file type; Golden references and test infrastructure can rise to a higher class; downgrading needs a real reduction of scope or risk; the maintainer cannot bypass the enforced GitHub checks (§5.1, §6.1). |
| D8 | Golden/test classification and who assigns a class? | Defaults by impact (cosmetic R1, new isolated Golden test R2, changed existing reference or affecting shared fixture R3, mechanism deciding trust in evidence across the project R4); not absolutes. Author proposes, auditor verifies when applicable, maintainer approves; doubt means the higher credible class until the opposite is shown; recorded in the PR. A class is reassessed when the PR changes (§6.1). |
| D9 | Audit of an older commit and later changes? | Not automatically covered; a targeted delta audit is allowed and may reuse evidence the later changes did not affect (conservatively). The final conclusion refers to the current PR head (§5.1). |
| D10 | What is a "clean auditable history"? | Understandable diff, traceable origin of changes, experimental interventions resolved, required gates met. Not every historical experimental commit must have passed every test; tangled experiments become a clean branch (§3.1). |
| D11 | How does this text become `docs/branching.md`? | Only after the final draft is approved, through a separate documentation branch and PR, each step separately approved. |
| D12 | Change the GitHub configuration? | No. Merge commit is allowed; squash and rebase are already disabled by the repository settings. The ruleset's own list of methods is left as it is. |

## 11. Remaining open points

No decision D1–D12 is reopened. The review findings in §12 have been addressed
in the text. Independent verification of the final delta and the maintainer's
ratification remain pending.

## 12. Independent review, round 1 (2026-10-21)

| ID | Finding | Verified | Resolution |
|---|---|---|---|
| A | Three roles can overlap in persons (author = maintainer; audit optional for R0/R1). | Yes: the text said "never collapsed into one" while the maintainer may also be the author. | Roles are distinguished from persons; the auditor is never the author when an audit is mandatory; the auditor role may stay unfilled for R0/R1 (§5.1). |
| B | CI does not test the PR head; it tests a GitHub test merge commit. | Yes: workflow has no `ref`; run 39633138383 shows checkout of `refs/remotes/pull/12/merge` at `ad2be61`, a merge of `c280e938` into `f193c0ac`. | Three identities defined: PR head, CI test merge commit, final merge commit (§5). Workflow unchanged. |
| C | Evidence identity by commit/tree is too narrow for Codelaxy. | Yes: `docs/architecture.md` I8 requires snapshot, relevant inputs, exact requirement identity, evidence schema version, provider identity/version, provider configuration fingerprint and toolchain identity. | PR record identity separated from I8 identity; I8 referenced explicitly; W named where a working tree is the subject (§6). |

### Original findings D–H

The original topics below are identified from the independent audit supplied
by the user. They are distinct from the later five P2 findings. The changes
are implemented; independent confirmation of this final delta remains pending.

| ID | Finding | Implemented resolution |
|---|---|---|
| D | Auditor reruns everything versus delta reuse | §5.1 separates inspection of actual CI records, auditor-directed targeted execution for affected proof obligations, and justified reuse. R3/R4 audits remain mandatory. |
| E | R2/R3 boundary for shared fixtures | §6 classifies by actual effect: using an existing fixture alone does not automatically mean R3; changing a shared fixture in a way that affects trustworthiness does. Uncertain impact uses the higher credible class. |
| F | Naming grammar contradicts examples | §2 permits short and extended names, with a roadmap ID when applicable; namespace meaning is unchanged. |
| G | Integration section still marked PROPOSAL | §4 shares the draft and ratification status of the whole policy; it is not a separate open proposal. P1.10 restrictions remain. |
| H | Unconditional Test Matrix update for R3 and snapshot-only alpha contract | R3 reviews applicability and updates only for changed relevant invariants, coverage or evidence status; otherwise the PR records why no update is needed. Alpha contracts name relevant requirements and evidence, with snapshot mapping where applicable. |

### Later findings P2-1–P2-5

These IDs replace the mistaken reuse of D–H for the five later topics.

| ID | Finding | Implemented resolution |
|---|---|---|
| P2-1 | Completeness of I8 identity | §6 includes relevant inputs, requirement kind and identity, evidence schema version, snapshot SchemaVersion and provider/configuration/toolchain identities. |
| P2-2 | Changed target branch | §5.1 requires reassessment of base changes and current test-merge CI. |
| P2-3 | Delta audit versus unconditional reruns | §6 invalidates automatic attribution after rewriting; §5.1 governs justified reuse and fresh verification. |
| P2-4 | Claim of no enforcement gaps | Header and §5 distinguish policy conventions from technical enforcement. |
| P2-5 | Snapshot Test Matrix imposed on all tests | Principles, alpha contracts and §6 distinguish snapshot coverage from other named requirements and invariants. |

Observation: strict required checks require the PR head branch to be up to date
with its target before merge. Updating a head branch that is behind its target
changes the PR head and invokes the later-commits rule in §5.1. Before that
update, a changed base can already affect the integrated state and the validity
of an earlier audit; the changed-target rule covers that reassessment.
`allow_update_branch` controls whether GitHub always suggests branch updates;
it does not decide whether updating a branch changes its head. With strict
checks, GitHub can offer an update even when this setting is false.
Whether CI actually reran on a particular new test merge must be verified from
that run; this observation does not claim an observed rerun.

## 13. How this draft was checked

- Read: `.github/workflows/ci.yml`, `docs/roadmap.md` (freeze exception and
  working rules), `docs/snapshot-test-matrix.md` (§7), the remote branch list
  of `origin`, the history of PRs #6–#11, and that the build-input files named
  in §6 exist at the repository root.
- Ran (read-only): `gh run view 39633138383 --log` (CI checkout of the test
  merge), `gh repo view`, `gh api …/branches/main/protection` (answer:
  not a classic branch protection), `gh api …/rulesets` including the ruleset
  detail, and `gh api repos/Revancze/Codelaxy` for the repository merge
  settings (after the user reported them; confirmed independently). The ref
  conflict shown in §2 was run in a throwaway repository.
- Final mechanical check (2026-10-21, by the co-author of this text, so **not
  independent**): every `§` reference resolves to a heading; decision rows
  D1–D12 are present and every cited D-id exists; all tables have a consistent
  column count; code fences are balanced; no tabs or CR characters. Live
  re-check: repository merge settings, the ruleset (including 0 required
  approvals and the two required checks) and the merged state of PRs #6–#11
  match the text. The subsequent independent audit supplied by the user
  reports the current remote branches as `main`, `feat/github-pages` and
  `test/m1-worktree-golden-001` (2026-10-21); the legacy name in §2 is historical.
- Not checked: that every statement in the user's private Git code of conduct
  matches this text (that document is not in the repository and was not
  available to read); behaviour of the ruleset in practice (it was read, not
  exercised). Decisions D9–D12 were recorded from the user's text of
  2026-10-21 and not re-verified against GitHub beyond what is stated in §5.
