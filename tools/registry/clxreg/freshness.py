"""IMP2-12 - currency of evidence (Q8) and propagation of a changed contract.

`assess(repo, evidence_commit, ref, scope_paths)`: CURRENT if the evidence commit is the reference, or an ancestor of it and the net diff between them
touches no path of `scope_paths`; STALE if it touches one (the changed paths are named) or, without `scope_paths`, whenever the reference is another
commit; UNDETERMINED (never CURRENT) if the commit is unknown here (advisory AD-09), not a full hash, or not an ancestor. The net diff is used, so a change
that was reverted again is no change. Renames count as a change of both the old and the new path.
`check_dependencies(snapshot, current)`: evidence stores the revisions of the requirements it depends on (`depends_on_revisions`); a raised revision makes
it STALE. What is not modelled in the snapshot cannot be claimed: no snapshot says nothing about contracts.
Masks are POSIX globs matched here (not by git, so no pathspec magic): `**` any directories, `*` within a name, `?` one character; a plain name also
covers everything under it; a trailing `/` means the directory's contents.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from .findings import advisory

CURRENT, STALE, UNDETERMINED = "CURRENT", "STALE", "UNDETERMINED"
_FULL = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class FreshnessError(RuntimeError):
    """The question cannot be put (bad repository, reference or mask): not a verdict about the evidence."""


@dataclass(frozen=True)
class Freshness:
    state: str
    reason: str
    changed: tuple
    findings: tuple


def _check_mask(mask):
    if not isinstance(mask, str) or not mask or mask.startswith("/") or "\\" in mask or "\0" in mask or ".." in mask.split("/"):
        raise FreshnessError(f"invalid scope mask {mask!r}")


def _regex(mask: str):
    out, i = [], 0
    while i < len(mask):
        if mask.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif mask.startswith("**", i):
            out.append(".*")
            i += 2
        elif mask[i] == "*":
            out.append("[^/]*")
            i += 1
        elif mask[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(mask[i]))
            i += 1
    return "".join(out)


def matches(path: str, mask: str) -> bool:
    _check_mask(mask)
    if mask.endswith("/"):
        return path.startswith(mask) and len(path) > len(mask)
    if re.fullmatch(_regex(mask), path):
        return True
    return "*" not in mask and "?" not in mask and path.startswith(mask + "/")


def _git(repo, *args) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except OSError as e:
        raise FreshnessError(f"cannot run git: {e}") from e


def _resolve(repo, ref) -> str:
    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\0" in ref:
        raise FreshnessError(f"invalid reference {ref!r}")
    p = _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    sha = p.stdout.decode("utf-8", "replace").strip()
    if p.returncode != 0 or not _FULL.fullmatch(sha):
        raise FreshnessError(f"{ref!r} is not a commit of the repository at {repo}")
    return sha


def assess(repo, evidence_commit, ref, scope_paths) -> Freshness:
    masks = list(scope_paths or [])
    for m in masks:
        _check_mask(m)
    head = _resolve(repo, ref if ref is not None else "HEAD")
    if not (isinstance(evidence_commit, str) and _FULL.fullmatch(evidence_commit)):
        return Freshness(UNDETERMINED, "the evidence commit is not a full hash", (), ())
    if _git(repo, "cat-file", "-e", evidence_commit + "^{commit}").returncode != 0:
        return Freshness(UNDETERMINED, f"commit {evidence_commit[:12]} is not available in this repository: currency cannot be verified", (),
                         (advisory("AD-09", evidence_commit[:12], "the commit of the evidence cannot be resolved locally; its currency was not verified"),))
    if evidence_commit == head:
        return Freshness(CURRENT, "the evidence is from the reference commit itself", (), ())
    anc = _git(repo, "merge-base", "--is-ancestor", evidence_commit, head).returncode
    if anc == 1:
        return Freshness(UNDETERMINED, f"the evidence commit {evidence_commit[:12]} is not an ancestor of {head[:12]}", (), ())
    if anc != 0:
        raise FreshnessError("git merge-base failed")
    if not masks:
        return Freshness(STALE, "no scope_paths: the evidence is current only on its own commit", (), ())
    d = _git(repo, "diff", "--name-only", "--no-renames", "-z", evidence_commit, head)
    if d.returncode != 0:
        raise FreshnessError("git diff failed: " + d.stderr.decode("utf-8", "replace").strip())
    names = [n.decode("utf-8", "surrogateescape") for n in d.stdout.split(b"\0") if n]
    hit = tuple(sorted(n for n in names if any(matches(n, m) for m in masks)))
    if hit:
        return Freshness(STALE, f"{len(hit)} path(s) of the scope changed since the evidence commit", hit, ())
    return Freshness(CURRENT, "no path of the scope changed since the evidence commit", (), ())


def check_dependencies(snapshot, current) -> Freshness:
    if snapshot is None or snapshot == {}:
        return Freshness(CURRENT, "no depends_on_revisions: contract changes are not modelled for this evidence", (), ())
    if not (isinstance(snapshot, dict) and isinstance(current, dict)):
        return Freshness(UNDETERMINED, "malformed revision snapshot", (), ())
    stale, unknown = [], []
    for ref in sorted(snapshot, key=str):
        have = snapshot[ref]
        if not (isinstance(ref, str) and type(have) is int and have >= 1):
            unknown.append(str(ref))
        elif ref not in current or type(current[ref]) is not int or current[ref] < have:
            unknown.append(ref)
        elif current[ref] > have:
            stale.append(ref)
    if stale:
        return Freshness(STALE, "a revision this evidence depends on has been raised", tuple(stale), ())
    if unknown:
        return Freshness(UNDETERMINED, "a dependency revision is unknown or went backwards: " + ", ".join(unknown), tuple(unknown), ())
    return Freshness(CURRENT, "every dependency is at the recorded revision", (), ())


def combine(*parts: Freshness) -> Freshness:
    for state in (STALE, UNDETERMINED):
        hit = [p for p in parts if p.state == state]
        if hit:
            return Freshness(state, "; ".join(p.reason for p in hit), tuple(c for p in hit for c in p.changed), tuple(f for p in parts for f in p.findings))
    return Freshness(CURRENT, "; ".join(p.reason for p in parts), (), tuple(f for p in parts for f in p.findings))


def propagate(evidences: dict, current_revisions: dict) -> dict:
    """evidence id -> Freshness of its dependencies alone (a contract change reaches only what depends on it)."""
    return {eid: check_dependencies((e or {}).get("depends_on_revisions"), current_revisions) for eid, e in sorted(evidences.items())}
