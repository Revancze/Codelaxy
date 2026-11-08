"""IMP2-10 - reader of `testrun` artifacts: TRX files and Markdown audit records. Read-only; `testrun` itself is never changed.

What it does: parse a TRX strictly (a damaged file is an error, not "no tests"), parse the header / table / "Unverified" section of a record, turn one
test into an observation, and write CANDIDATE evidence (no id, no class, a new directory only) that carries the hashes of what was read.
What it refuses to do: infer that anything is valid from the existence of a report. A suite-level PASS says nothing about a given test; a test that the
record lists as returned at a platform guard never ran its body; a guard list the record truncated cannot show that a test is NOT in it.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from . import canon, dirty

_NS = "{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}"
_SHA = re.compile(r"[0-9a-f]{64}")


class TrxError(ValueError):
    pass


class RecordError(ValueError):
    pass


class TestrunError(RuntimeError):
    __test__ = False                 # not a test class for unittest / pytest collection


# --- TRX ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Trx:
    start: str | None
    finish: str | None
    tests: dict
    counts: dict
    total: int
    summary_outcome: str | None
    counters: dict
    counters_consistent: bool


def parse_trx(data: bytes) -> Trx:
    if b"<!DOCTYPE" in data.upper():
        raise TrxError("a document type declaration is not accepted")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise TrxError(f"not well-formed XML (a damaged or truncated file): {e}") from e
    if root.tag != _NS + "TestRun":
        raise TrxError(f"the root element is {root.tag!r}, not a TRX TestRun")
    results = root.find(_NS + "Results")
    if results is None:
        raise TrxError("no Results element")
    tests, counts, total = {}, {}, 0
    for r in results.findall(_NS + "UnitTestResult"):
        name, outcome = r.get("testName"), r.get("outcome")
        if not name or not outcome:
            raise TrxError("a UnitTestResult without testName or outcome")
        tests.setdefault(name, []).append(outcome)
        counts[outcome] = counts.get(outcome, 0) + 1
        total += 1
    times = root.find(_NS + "Times")
    summary = root.find(_NS + "ResultSummary")
    counters = {}
    if summary is not None and summary.find(_NS + "Counters") is not None:
        for k, v in summary.find(_NS + "Counters").attrib.items():
            try:
                counters[k] = int(v)
            except ValueError:
                raise TrxError(f"counter {k} is not a number") from None
    return Trx(times.get("start") if times is not None else None, times.get("finish") if times is not None else None, tests, counts, total,
               summary.get("outcome") if summary is not None else None, counters, "total" not in counters or counters["total"] == total)


# --- audit records ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceRow:
    platform: str
    environment: str
    verdict: str
    executed: int
    passed: int
    failed: int
    not_executed: int


@dataclass(frozen=True)
class Guard:
    platform: str
    total: int
    names: tuple
    truncated: bool


@dataclass(frozen=True)
class Record:
    timestamp: str
    repository: str
    branch: str
    head: str
    tree_state: str
    scope: str
    evidence: tuple
    copies: dict
    guards: dict
    mutation_not_run: bool
    executor_text: str | None
    independent: bool = field(default=False)       # a record cannot make itself independent: never True


_TITLE = re.compile(r"^# Audit record .* - (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\s*$")
_BULLET = re.compile(r"^- (repository|branch|HEAD|working tree|scope): (.*?)\s*$")
_GUARD = re.compile(r"^(\d+) passing test\(s\) returned at a platform guard on (\w+) \(their body never ran\): (.*)$")
_COPY = re.compile(r"(win|linux): (.+?)(?=; (?:win|linux): |$)")
_HEAD = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _split_names(text: str) -> list:
    out, depth, cur, i = [], 0, [], 0
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if depth == 0 and text.startswith(", ", i):
            out.append("".join(cur))
            cur, i = [], i + 2
            continue
        cur.append(c)
        i += 1
    if cur:
        out.append("".join(cur))
    return out


def parse_record(text: str) -> Record:
    lines = text.split("\n")
    first = next((ln for ln in lines if ln.strip()), "")
    m = _TITLE.match(first.rstrip("\r"))
    if not m:
        raise RecordError("not an audit record: the title line with the time is missing")
    head = {}
    rows, copies, guards, bullets = [], {}, {}, []
    section = ""
    for raw in lines:
        ln = raw.rstrip("\r")
        if ln.startswith("## "):
            section = ln[3:].strip().lower()
            continue
        b = _BULLET.match(ln)
        if b and not section:
            head[b.group(1)] = b.group(2)
        elif section == "evidence" and ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if cells and cells[0] not in ("platform",) and not set(cells[0]) <= {"-", ":"}:
                if len(cells) != 7:
                    raise RecordError(f"an evidence row needs 7 cells: {ln[:60]!r}")
                try:
                    nums = [int(c) for c in cells[3:]]
                except ValueError:
                    raise RecordError(f"the counts of an evidence row are not numbers: {ln[:60]!r}") from None
                rows.append(EvidenceRow(cells[0], cells[1], cells[2], *nums))
        elif section == "evidence" and ln.startswith("Working copies"):
            _, _, rest = ln.partition("): ")
            copies.update({k: v.strip() for k, v in _COPY.findall(rest)})
        elif section.startswith("unverified") and ln.startswith("- "):
            bullets.append(ln[2:])
    for key in ("repository", "branch", "HEAD", "working tree", "scope"):
        if key not in head:
            raise RecordError(f"the header line {key!r} is missing")
    if not _HEAD.fullmatch(head["HEAD"]):
        raise RecordError("HEAD is not a full commit hash")
    if not rows:
        raise RecordError("the evidence table has no rows")
    for bl in bullets:
        g = _GUARD.match(bl)
        if g:
            body = g.group(3).strip()
            ellipsis = body.endswith("...")
            names = tuple(_split_names(body[:-3].rstrip() if ellipsis else body))
            guards[g.group(2)] = Guard(g.group(2), int(g.group(1)), names, ellipsis or len(names) < int(g.group(1)))
    tw = head["working tree"]
    state = "DIRTY" if tw.upper().startswith("DIRTY") else "CLEAN" if tw.lower().startswith("clean") else "UNKNOWN"
    executor = next((b for b in bullets if b.startswith("this record was produced by")), None)
    return Record(m.group(1), head["repository"], head["branch"], head["HEAD"], state, head["scope"], tuple(rows), copies, guards,
                  any(b.startswith("mutation checks were not run") for b in bullets), executor)


# --- one test as an observation ------------------------------------------------------------------------------------------------------
def guard_status(name: str, guard: Guard | None) -> str:
    if guard is not None and name in guard.names:
        return "LISTED"
    if guard is not None and guard.truncated:
        return "NOT_LISTED_TRUNCATED_LIST"
    return "NOT_LISTED_COMPLETE_LIST"


def observation(name: str, trx: Trx, guard: Guard | None) -> dict:
    """What the TRX and the record together allow to say about ONE test. PASS only for a test that Passed and is provably not a guarded one."""
    results = trx.tests.get(name)
    if not results:
        return {"name": name, "outcome": "ABSENT", "guard": "NOT_FOUND"}
    g = guard_status(name, guard)
    if "Failed" in results:
        outcome = "FAIL"
    elif all(r == "NotExecuted" for r in results):
        outcome = "SKIP"
    elif all(r == "Passed" for r in results):
        outcome = {"LISTED": "ABSENT", "NOT_LISTED_TRUNCATED_LIST": "UNVERIFIED", "NOT_LISTED_COMPLETE_LIST": "PASS"}[g]
    else:
        outcome = "UNVERIFIED"
    return {"name": name, "outcome": outcome, "guard": g}


# --- candidate evidence ----------------------------------------------------------------------------------------------------------------
def _read(path) -> bytes:
    return Path(path).read_bytes()


def _read_stable(path) -> bytes:
    a = _read(path)
    if _read(path) != a:
        raise TestrunError(f"{path} changed while it was being read")
    return a


def candidate_evd(record_path, trx_path, platform, tests, provenance=None) -> dict:
    try:
        rec_bytes = _read_stable(record_path)
    except OSError as e:
        raise TestrunError(f"cannot read the record: {e}") from e
    try:
        rec = parse_record(rec_bytes.decode("utf-8"))
    except (UnicodeDecodeError, RecordError) as e:
        raise TestrunError(f"the record is not usable: {e}") from e
    row = next((e for e in rec.evidence if e.platform == platform), None)
    if row is None:
        raise TestrunError(f"the record has no evidence row for the platform {platform!r}")
    artifacts = [{"role": "audit-record", "locator": str(record_path), "sha256": hashlib.sha256(rec_bytes).hexdigest()}]
    trx = None
    availability, integrity = "AVAILABLE", "NOT_CHECKED"
    try:
        trx_bytes = _read_stable(trx_path)
    except FileNotFoundError:
        availability = "UNLOCATED"
    except OSError as e:
        raise TestrunError(f"cannot read the TRX: {e}") from e
    else:
        artifacts.append({"role": "trx", "locator": str(trx_path), "sha256": hashlib.sha256(trx_bytes).hexdigest()})
        try:
            trx = parse_trx(trx_bytes)
            integrity = "HASH_CHECKED"
        except TrxError:
            trx = None
    observations = [observation(n, trx, rec.guards.get(platform)) for n in tests] if trx is not None else []
    outs = [o["outcome"] for o in observations]
    result = "FAIL" if "FAIL" in outs else "PASS" if outs and all(o == "PASS" for o in outs) else "INCONCLUSIVE"
    env = {"os": platform, "environment": row.environment}
    if "nen\u00ed to CI" in row.environment or "not CI" in row.environment or "not the CI" in row.environment:
        env["ci"] = False
    cand = {
        "candidate": True, "schema_version": 1, "type": "EVD", "result": result,
        "performed_at": trx.finish if trx is not None and trx.finish else rec.timestamp,
        "subject": {"repository": rec.repository, "branch": rec.branch, "commit": rec.head, "tree_state": rec.tree_state},
        "platform": env,
        "executor": {"kind": "agent", "name": "gitrun audit", "independence": "author"},
        "artifacts": artifacts, "source": {"availability": availability, "integrity": integrity},
        "observations": observations,
        "suite": {"verdict": row.verdict, "executed": row.executed, "passed": row.passed, "failed": row.failed, "not_executed": row.not_executed},
        "provenance": {"assessed": False} if provenance is None else {"assessed": True, **provenance},
    }
    if trx is not None:
        cand["counts"] = {"passed": trx.counts.get("Passed", 0), "failed": trx.counts.get("Failed", 0), "skipped": trx.counts.get("NotExecuted", 0), "total": trx.total}
    return cand


def write_candidates(out_dir, candidates) -> list:
    out = Path(out_dir)
    if out.exists():
        raise TestrunError(f"the output directory exists: {out}")
    out.mkdir()
    names = []
    for i, c in enumerate(candidates, 1):
        name = f"EVD-candidate-{i:04d}.json"
        canon.write_record(out / name, c)
        names.append(name)
    return names


# --- facts for the provenance checklist (IMP2-11) -------------------------------------------------------------------------------------
_COPY_NAME = re.compile(r"-(win|linux)-(\d{8}-\d{6})-([0-9a-f]{8})$")
_RUN_NAME = re.compile(r"-(\d{8}-\d{6})-([0-9a-f]{8})-(win|linux)$")


def gather_facts(rec: Record, platform: str, trx: Trx, trx_path, test_name: str, copy_dir=None, manifest_at_run=None, env_file_text=None) -> dict:
    """The facts provenance.assess() judges, taken from the record, the TRX and the copy. Whatever cannot be established stays absent."""
    row = next((e for e in rec.evidence if e.platform == platform), None)
    copy_name = (rec.copies.get(platform) or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    cm, rm = _COPY_NAME.search(copy_name), _RUN_NAME.search(Path(trx_path).parent.name)
    exists = copy_dir is not None and Path(copy_dir).is_dir()
    has_git = exists and (Path(copy_dir) / ".git").exists()
    head = None
    if has_git:
        try:
            head = dirty._git(copy_dir, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        except dirty.ManifestError:
            head = None
    now = None
    if exists and manifest_at_run is not None and manifest_at_run.get("kind") == "tree":
        m = dirty.tree_manifest(copy_dir, tuple(manifest_at_run.get("excludes", ())))
        now = {"kind": "tree", "digest": dirty.digest(m), "excludes": m["excludes"]}
    env_os = next((ln.split()[0] for ln in (env_file_text or "").splitlines() if ln.split()[:1] in (["Linux"], ["Windows"])), None)
    return {
        "record": {"run_id": cm.group(3) if cm else None, "stamp": cm.group(2) if cm else None, "head": rec.head, "platform": platform, "timestamp": rec.timestamp},
        "run_dir": {"name": Path(trx_path).parent.name, "id": rm.group(2) if rm else None, "stamp": rm.group(1) if rm else None, "platform": rm.group(3) if rm else None},
        "trx": {"present": True, "start": trx.start, "finish": trx.finish, "tests": trx.tests},
        "copy": {"exists": exists, "name": copy_name, "id": cm.group(3) if (cm and exists) else None, "stamp": cm.group(2) if (cm and exists) else None,
                 "platform": cm.group(1) if (cm and exists) else None, "has_git": has_git, "head": head},
        "manifest_at_run": manifest_at_run, "manifest_now": now,
        "environment": {"trx_prefix": Path(trx_path).name.split("-", 1)[0], "record_environment": row.environment if row else None, "env_file_os": env_os,
                        "utc_offset": (manifest_at_run or {}).get("utc_offset")},
        "test": {"name": test_name, "guard": guard_status(test_name, rec.guards.get(platform))},
    }
