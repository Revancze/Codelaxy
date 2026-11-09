"""IMP2-11 (b) - provenance checklist (TD-14): may the content fingerprint of a DIRTY run be trusted?

A DIRTY run can be PROVISIONAL evidence only when all six points are PROVEN from the facts given; any point not shown makes the evidence UNBOUND and
the result names the points. Missing, malformed or contradictory facts never prove a point (and never raise). Nothing is inferred from the existence of
a report; every point carries the basis (or the absence) it rests on.
  1 run-identity          run id, timestamp and platform agree between the record, the run directory and the copy; the TRX finished before the record
  2 head                  the HEAD the copy descends from (from its .git or from the manifest taken at run time) equals the HEAD in the record
  3 manifest-at-run       a content manifest was captured before or at the start of the run
  4 platform-environment  platform and environment agree (and, on Linux, the environment file says Linux)
  5 copy-unchanged        the manifest of the copy now equals the one taken at run time, under the same exclusions
  6 test-executed         the TRX has the test and every result is Passed, and the record's guard list is complete and does not name it
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

POINT_NAMES = {1: "run-identity", 2: "head", 3: "manifest-at-run", 4: "platform-environment", 5: "copy-unchanged", 6: "test-executed"}
_HEX_HEAD = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA = re.compile(r"[0-9a-f]{64}")
_FRACTION = re.compile(r"(\.\d{6})\d+")


@dataclass(frozen=True)
class Point:
    n: int
    name: str
    holds: bool
    basis: str


@dataclass(frozen=True)
class Assessment:
    points: tuple

    @property
    def unmet(self) -> tuple:
        return tuple(p.name for p in self.points if not p.holds)

    @property
    def proven(self) -> bool:
        return not self.unmet


def _d(x):
    return x if isinstance(x, dict) else {}


def _ts(s, utc_offset=None):
    """An instant in UTC. A naive clock requires an explicitly recorded offset."""
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?", s):
        return None
    try:
        value = datetime.fromisoformat(_FRACTION.sub(r"\1", s))
        if value.tzinfo is None:
            if not isinstance(utc_offset, str) or not re.fullmatch(r"[+-]\d{2}:\d{2}", utc_offset):
                return None
            offset = datetime.fromisoformat("2000-01-01T00:00:00" + utc_offset).tzinfo
            value = value.replace(tzinfo=offset)
        return value.astimezone(timezone.utc)
    except ValueError:
        return None


def assess(facts) -> Assessment:
    f = _d(facts)
    rec, rd, trx, cp = _d(f.get("record")), _d(f.get("run_dir")), _d(f.get("trx")), _d(f.get("copy"))
    mar, mnow, env, test = _d(f.get("manifest_at_run")), _d(f.get("manifest_now")), _d(f.get("environment")), _d(f.get("test"))
    offset = env.get("utc_offset")
    points = [_identity(rec, rd, trx, cp, offset), _head(rec, cp, mar), _manifest_at_run(mar, trx, offset), _platform(rec, rd, cp, env), _unchanged(cp, mar, mnow), _executed(trx, test)]
    return Assessment(tuple(Point(i + 1, POINT_NAMES[i + 1], ok, why) for i, (ok, why) in enumerate(points)))


def _identity(rec, rd, trx, cp, utc_offset=None):
    rid = rec.get("run_id")
    if not (isinstance(rid, str) and rid and rid == rd.get("id") == cp.get("id")):
        return False, f"run id differs or is missing (record {rid!r}, run directory {rd.get('id')!r}, copy {cp.get('id')!r})"
    st = rec.get("stamp")
    if not (isinstance(st, str) and st and st == rd.get("stamp") == cp.get("stamp")):
        return False, "the date-time stamp of the record, the run directory and the copy do not agree"
    pl = rec.get("platform")
    if not (isinstance(pl, str) and pl and pl == rd.get("platform") == cp.get("platform")):
        return False, "the platform of the record, the run directory and the copy do not agree"
    if trx.get("present") is not True:
        return False, "no TRX of the run is present"
    start, finish, written = _ts(trx.get("start"), utc_offset), _ts(trx.get("finish"), utc_offset), _ts(rec.get("timestamp"), utc_offset)
    # the record has a resolution of one second: compare the TRX finish at that resolution
    if not (start and finish and written) or not start <= finish or finish.replace(microsecond=0) > written or written.date() != finish.date():
        return False, "the TRX times are missing or not before the record time of the same day"
    return True, f"run {rid}, stamp {st}, platform {pl}; TRX {finish.time()} <= record {written.time()}"


def _head(rec, cp, mar):
    want = rec.get("head")
    have = cp.get("head") or mar.get("head")
    if not (isinstance(want, str) and _HEX_HEAD.fullmatch(want)):
        return False, "the record names no full HEAD"
    if not (isinstance(have, str) and _HEX_HEAD.fullmatch(have)):
        return False, "the copy carries no HEAD (no .git) and the manifest records none: it is not shown what the copy descends from"
    return (have == want), ("copy and record agree on HEAD " + want[:12]) if have == want else f"the copy descends from {have[:12]}, the record says {want[:12]}"


def _manifest_at_run(mar, trx, utc_offset=None):
    dg = mar.get("digest")
    if mar.get("kind") not in ("tree", "git-dirty") or not (isinstance(dg, str) and _SHA.fullmatch(dg)):
        return False, "no content manifest captured at run time (the tool does not write one)"
    cap, start = _ts(mar.get("captured_at"), utc_offset), _ts(trx.get("start"), utc_offset)
    if not (cap and start) or cap > start:
        return False, "the manifest was not captured before or at the start of the run"
    return True, f"manifest {dg[:12]} captured {cap.time()} <= run start {start.time()}"


def _platform(rec, rd, cp, env):
    pl = rec.get("platform")
    if not (isinstance(pl, str) and pl in ("win", "linux") and pl == env.get("trx_prefix") == rd.get("platform") == cp.get("platform")):
        return False, "platform of the record, the run directory, the copy and the TRX name do not agree"
    text = env.get("record_environment")
    if not isinstance(text, str):
        return False, "the record states no environment"
    if pl == "win" and not text.startswith("Windows"):
        return False, f"the record environment {text[:30]!r} is not Windows"
    if pl == "linux":
        if not (text.startswith("WSL") or text.startswith("Linux")):
            return False, f"the record environment {text[:30]!r} is not Linux"
        if env.get("env_file_os") != "Linux":
            return False, "the environment file of the run does not say Linux"
    return True, f"{pl}: {text[:40]}"


def _unchanged(cp, mar, mnow):
    a, b = mar.get("digest"), mnow.get("digest")
    if cp.get("exists") is not True:
        return False, "the working copy no longer exists"
    if not (isinstance(a, str) and _SHA.fullmatch(a) and isinstance(b, str) and _SHA.fullmatch(b)):
        return False, "no manifest at run time or no manifest of the copy now: a change after the test cannot be excluded"
    if mar.get("kind") != mnow.get("kind") or mar.get("excludes") != mnow.get("excludes"):
        return False, "the manifests were taken under different rules (kind or excluded directories)"
    return (a == b), ("the copy still equals the manifest taken at run time" if a == b else "the copy differs from the manifest taken at run time")


def _executed(trx, test):
    name, results = test.get("name"), _d(trx.get("tests")).get(test.get("name") if isinstance(test.get("name"), str) else None)
    if not (isinstance(name, str) and name):
        return False, "no test named"
    if not (isinstance(results, list) and results and all(r == "Passed" for r in results)):
        return False, f"the TRX does not show {name} as Passed in every result ({results!r})"
    if test.get("guard") != "NOT_LISTED_COMPLETE_LIST":
        return False, f"the record's platform-guard list does not allow concluding that the body ran ({test.get('guard')!r})"
    return True, f"{name}: Passed x{len(results)}, not in a complete guard list"
