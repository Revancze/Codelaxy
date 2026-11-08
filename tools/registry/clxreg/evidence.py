"""IMP2-09 - evidence classes, qualification and the gate (TD-13).

An evidence class says HOW FAR an observation is tied to a code state; it is not a state of a requirement:
  COMMIT_BOUND       a clean tree and a full commit hash
  PROVISIONAL        a DIRTY tree whose content fingerprint is backed by a provenance in which ALL six points (provenance.py) are proven
  UNBOUND            DIRTY or unknown tree without such proof, or a commit that is not a full hash
  UNLOCATED          a claim without an available artifact
  UNVERIFIED_RESULT  an artifact exists, but its hash, platform, executor or result cannot be shown
Only a COMMIT_BOUND evidence can support VERIFIED, and only when every other condition (Q1-Q9 of the schema) also holds. PROVISIONAL is listed in a
report as "provisionally supported" with its fingerprint and provenance, changes no derived state, is not counted as DONE and never satisfies a gate.
A missing, incomplete or changed evidence never produces success: it degrades to a lower class or to an unmet condition that is named.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from . import provenance
from .findings import data_error, evidence_missing

COMMIT_BOUND, PROVISIONAL, UNBOUND, UNLOCATED, UNVERIFIED_RESULT = "COMMIT_BOUND", "PROVISIONAL", "UNBOUND", "UNLOCATED", "UNVERIFIED_RESULT"
CLASSES = (COMMIT_BOUND, PROVISIONAL, UNBOUND, UNLOCATED, UNVERIFIED_RESULT)
RESULTS = ("PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN")
_INDEPENDENCE = {"none": 0, "author": 0, "independent": 1, "owner": 2}
_FULL = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Classification:
    cls: str
    reasons: tuple


def _d(x):
    return x if isinstance(x, dict) else {}


def classify(evd) -> Classification:
    if not isinstance(evd, dict):
        return Classification(UNVERIFIED_RESULT, ("not an evidence record",))
    src, arts = _d(evd.get("source")), evd.get("artifacts")
    why = []
    if src.get("availability") != "AVAILABLE":
        why.append(f"availability is {src.get('availability')!r}, not AVAILABLE")
    if not (isinstance(arts, list) and arts):
        why.append("no artifact")
    if why:
        return Classification(UNLOCATED, tuple(why))
    if src.get("integrity") != "HASH_CHECKED":
        why.append(f"integrity is {src.get('integrity')!r}, not HASH_CHECKED")
    for i, a in enumerate(arts):
        a = _d(a)
        if not (isinstance(a.get("sha256"), str) and _SHA.fullmatch(a["sha256"]) and a.get("locator") and a.get("role")):
            why.append(f"artifact #{i + 1} lacks role, locator or a valid sha256")
    if not _d(evd.get("platform")).get("os"):
        why.append("no platform")
    ex = _d(evd.get("executor"))
    if ex.get("kind") not in ("ci", "human", "agent") or ex.get("independence") not in ("author", "independent", "owner"):
        why.append("the executor is missing or invalid")
    if evd.get("result") not in RESULTS:
        why.append(f"result {evd.get('result')!r} is not one of {', '.join(RESULTS)}")
    if why:
        return Classification(UNVERIFIED_RESULT, tuple(why))
    sub = _d(evd.get("subject"))
    commit_ok = isinstance(sub.get("commit"), str) and bool(_FULL.fullmatch(sub["commit"]))
    state = sub.get("tree_state")
    if state == "CLEAN":
        return Classification(COMMIT_BOUND, ()) if commit_ok else Classification(UNBOUND, ("the commit is not a full hash",))
    if state != "DIRTY":
        return Classification(UNBOUND, (f"tree state is {state!r}",))
    if not commit_ok:
        why.append("the commit is not a full hash")
    if not (isinstance(sub.get("fingerprint"), str) and _SHA.fullmatch(sub["fingerprint"])):
        why.append("no content fingerprint")
    pv = _d(evd.get("provenance"))
    if pv.get("assessed") is not True:
        why.append("provenance was not assessed")
    else:
        points = pv.get("points")
        unproven = [p.get("name") for p in points if isinstance(p, dict) and p.get("holds") is not True] if isinstance(points, list) else None
        names = [p.get("name") for p in points if isinstance(p, dict)] if isinstance(points, list) else []
        if not (isinstance(points, list) and sorted(names) == sorted(provenance.POINT_NAMES.values())):
            why.append("the six provenance points are not recorded")
        elif unproven:
            why.append("provenance not proven: " + ", ".join(unproven))
        elif pv.get("proven") is not True:
            why.append("provenance not proven")
    return Classification(UNBOUND, tuple(why)) if why else Classification(PROVISIONAL, ())


def attach_provenance(evd: dict, assessment, fingerprint: str) -> dict:
    """A copy of the evidence with the fingerprint and the six assessed points recorded; the class is NOT stored, it is derived."""
    out = copy.deepcopy(evd)
    out.setdefault("subject", {})["fingerprint"] = fingerprint
    out["provenance"] = {"assessed": True, "proven": assessment.proven, "unmet": list(assessment.unmet),
                         "points": [{"n": p.n, "name": p.name, "holds": p.holds, "basis": p.basis} for p in assessment.points]}
    return out


def validate_evd(evd, rec="evidence") -> list:
    """DE-09: an EVD without an identifiable source."""
    out = []
    if not isinstance(evd, dict):
        return [data_error("DE-09", rec, "an evidence record must be a JSON object")]
    for f in ("subject", "platform", "executor", "performed_at", "result"):
        if not evd.get(f):
            out.append(data_error("DE-09", rec, f"missing {f}: the evidence cannot be identified"))
    if _d(evd.get("subject")) and not _d(evd.get("subject")).get("commit"):
        out.append(data_error("DE-09", rec, "missing subject.commit"))
    if _d(evd.get("source")).get("availability") == "AVAILABLE" and not any(isinstance(a, dict) and _SHA.fullmatch(str(a.get("sha256"))) for a in (evd.get("artifacts") or [])):
        out.append(data_error("DE-09", rec, "AVAILABLE evidence needs an artifact with a sha256"))
    return out


# --- qualification (Q1-Q9) -------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Qualification:
    qualifies: bool
    failed: tuple
    cls: str
    stale: bool          # every condition holds except Q8: it was proven once and is not proven today


def observation_outcomes(observations) -> dict:
    """Every observation of a test must pass; list order cannot hide a failure."""
    obs = {}
    for o in observations or []:
        if isinstance(o, dict) and isinstance(o.get("name"), str):
            name, outcome = o.get("name"), o.get("outcome")
            obs[name] = outcome if name not in obs else "PASS" if obs[name] == outcome == "PASS" else "INCONCLUSIVE"
    return obs


def qualify(evd: dict, scn: dict, ctx: dict) -> Qualification:
    """May `evd` satisfy acceptance condition ctx['acceptance'] of requirement ctx['requirement'] on platform ctx['platform']?
    ctx: requirement, revisions (revisions of the requirement that count as the current one), acceptance, platform, persistence, freshness
    (CURRENT / STALE / UNDETERMINED / None), required_independence, scenario_revisions, newer_fail (a newer FAIL superseded this evidence)."""
    cl = classify(evd)
    e, s = _d(evd), _d(scn)
    failed = []
    if cl.cls != COMMIT_BOUND:
        failed.append(f"CLASS: {cl.cls} cannot support VERIFIED" + (f" ({'; '.join(cl.reasons)})" if cl.reasons else ""))
    if e.get("result") != "PASS" or (s.get("method") == "mutation" and not e.get("baseline")):
        failed.append("Q1: result is not PASS" if e.get("result") != "PASS" else "Q1: a mutation needs a green baseline")
    if e.get("lifecycle") != "ACTIVE" or ctx.get("newer_fail"):
        failed.append("Q2: not ACTIVE or superseded by a newer FAIL")
    src = _d(e.get("source"))
    if src.get("availability") != "AVAILABLE" or src.get("integrity") != "HASH_CHECKED":
        failed.append("Q3: the source is not available and hash-checked")
    ev = [x for x in (e.get("evidences") or []) if isinstance(x, dict)]
    if not any(x.get("requirement") == ctx.get("requirement") and x.get("acceptance") == ctx.get("acceptance") and x.get("requirement_revision") in ctx.get("revisions", ())
               for x in ev):
        failed.append("Q4: the evidence does not bind this requirement revision and condition")
    ver = [v for v in (s.get("verifies") or []) if isinstance(v, dict)]
    if not (e.get("scenario_revision") in ctx.get("scenario_revisions", ()) and any(
            v.get("requirement") == ctx.get("requirement") and v.get("acceptance") == ctx.get("acceptance") and v.get("adequacy") == "ACCEPTED" and v.get("basis") and v.get("requirement_revision") in ctx.get("revisions", ()) for v in ver)):
        failed.append("Q5: the scenario is not accepted as adequate (or its revision is not current)")
    if _d(e.get("platform")).get("os") != ctx.get("platform"):
        failed.append("Q6: the evidence is from another platform")
    need = max(_INDEPENDENCE.get(ctx.get("required_independence", "none"), 0), _INDEPENDENCE.get(s.get("independence_required", "none"), 0))
    if _INDEPENDENCE.get(_d(e.get("executor")).get("independence"), -1) < need:
        failed.append("Q7: not independent enough")
    q8 = ctx.get("persistence") != "ONCE" and ctx.get("freshness") != "CURRENT"
    if ctx.get("persistence") not in ("ONCE", "CONTINUOUS", "UNSPECIFIED", None):
        failed.append("Q8: invalid persistence policy")
    if q8:
        failed.append(f"Q8: not current ({ctx.get('freshness')!r})")
    if s.get("observation_required") or s.get("method") in ("test", "mutation"):
        tests = [i.get("test") for i in (s.get("implementation") or []) if isinstance(i, dict) and i.get("test")]
        obs = observation_outcomes(e.get("observations"))
        if not tests or any(obs.get(t) != "PASS" for t in tests):
            failed.append("Q9: not every implementing test has a PASS observation (EM-09)")
    stale = bool(failed) and all(f.startswith("Q8") for f in failed) and ctx.get("freshness") == "STALE"
    return Qualification(not failed, tuple(failed), cl.cls, stale)


# --- derivation, report, gate ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Derived:
    verification: str
    effective_status: str
    conditions: dict          # acceptance id -> SATISFIED / STALE / FAILED / OPEN / UNDETERMINED
    provisional: tuple        # (evidence id, acceptance, platform, fingerprint, unmet) - shown, never counted
    findings: tuple


_EFFECTIVE = {"VERIFIED": "DONE", "PARTIALLY_VERIFIED": "PARTIAL", "UNKNOWN": "UNKNOWN", "UNVERIFIED": "UNVERIFIED", "STALE": "UNVERIFIED", "FAILED": "OPEN"}


def derive(req: dict, scenarios: dict, evidences: dict, env: dict | None = None) -> Derived:
    """Derive the state of one requirement. scenarios / evidences: id -> record. env: {'freshness': {evidence id: CURRENT|STALE|UNDETERMINED}}."""
    env = env or {}
    rid = req.get("id")
    findings = []
    if req.get("definition") == "UNRESOLVED":
        findings.append(evidence_missing("EM-01", rid, "the requirement is UNRESOLVED: nothing can verify it"))
        return Derived("UNKNOWN", "UNKNOWN", {}, (), tuple(findings))
    conds, provisional = {}, []
    default_platforms = _d(req.get("applies_to")).get("platforms") or ["any"]
    for ac in req.get("acceptance") or []:
        acid = ac.get("id")
        if ac.get("kind", "evidence") != "evidence":
            continue
        if ac.get("resolved") is False:
            conds[acid] = "UNDETERMINED"
            continue
        platforms = _d(ac.get("requires")).get("platforms") or default_platforms
        states = []
        for pl in platforms:
            states.append(_platform_state(req, ac, pl, scenarios, evidences, env, provisional, findings))
        conds[acid] = "FAILED" if "FAILED" in states else "SATISFIED" if all(s == "SATISFIED" for s in states) else \
            "STALE" if all(s in ("SATISFIED", "STALE") for s in states) else "PARTIAL" if "SATISFIED" in states else "OPEN"
    vals = list(conds.values())
    if not vals:
        v = "UNVERIFIED"
    elif "UNDETERMINED" in vals:
        v = "UNKNOWN"
    elif "FAILED" in vals:
        v = "FAILED"
    elif all(x == "SATISFIED" for x in vals):
        v = "VERIFIED"
    elif "SATISFIED" in vals or "PARTIAL" in vals:
        v = "PARTIALLY_VERIFIED"
    elif "STALE" in vals:
        v = "STALE"
    else:
        v = "UNVERIFIED"
    return Derived(v, _EFFECTIVE[v], conds, tuple(provisional), tuple(findings))


def _platform_state(req, ac, platform, scenarios, evidences, env, provisional, findings):
    rid, acid = req.get("id"), ac.get("id")
    best = "OPEN"
    relevant = [eid for eid in sorted(evidences)
                if any(isinstance(x, dict) and x.get("requirement") == rid and x.get("acceptance") == acid for x in (_d(evidences[eid]).get("evidences") or []))
                and (platform == "any" or _d(_d(evidences[eid]).get("platform")).get("os") in (platform, None))]
    superseded_by_fail = {eid: any(_d(o).get("result") == "FAIL" and eid in (_d(o).get("supersedes") or []) for o in evidences.values()) for eid in relevant}
    # a recorded, active failure blocks first, whatever its class and whatever passes exist next to it; only its own lifecycle can lift it
    if any(_d(evidences[eid]).get("result") == "FAIL" and _d(evidences[eid]).get("lifecycle") == "ACTIVE" for eid in relevant):
        return "FAILED"
    any_evd = bool(relevant)
    for eid in relevant:
        e = evidences[eid]
        newer = superseded_by_fail[eid]
        scn = scenarios.get(_d(e).get("scenario"), {})
        ctx = {"requirement": rid, "revisions": tuple(env.get("equivalent_revisions", {}).get(rid, (req.get("revision"),))), "acceptance": acid,
               "platform": platform if platform != "any" else _d(_d(e).get("platform")).get("os"), "persistence": req.get("persistence"),
               "freshness": env.get("freshness", {}).get(eid), "required_independence": _d(ac.get("requires")).get("independence", "none"),
               "scenario_revisions": tuple(env.get("equivalent_scenario_revisions", {}).get(_d(e).get("scenario"), (scn.get("revision"),))), "newer_fail": newer}
        q = qualify(e, scn, ctx)
        cl = classify(e)
        if cl.cls == PROVISIONAL:
            sub = _d(_d(e).get("subject"))
            provisional.append((eid, acid, platform, sub.get("fingerprint"), tuple(_d(_d(e).get("provenance")).get("unmet", ()))))
        if q.qualifies:
            return "SATISFIED"
        if q.stale:
            best = "STALE"
        else:
            codes = [f.split(":")[0] for f in q.failed]
            if cl.cls == UNLOCATED:
                findings.append(evidence_missing("EM-04", eid, "the evidence is not located: " + "; ".join(cl.reasons)))
            elif cl.cls in (UNBOUND, PROVISIONAL):
                findings.append(evidence_missing("EM-12", eid, f"the evidence is {cl.cls} (DIRTY or unproven tree); it cannot verify"))
            elif cl.cls == UNVERIFIED_RESULT:
                findings.append(evidence_missing("EM-04", eid, "the result cannot be verified: " + "; ".join(cl.reasons)))
            if "Q9" in codes:
                findings.append(evidence_missing("EM-09", eid, "no PASS observation for every implementing test"))
    if not any_evd:
        findings.append(evidence_missing("EM-08" if len(_d(req.get("applies_to")).get("platforms") or []) > 1 else "EM-02", f"{rid}/{acid}",
                                          f"no evidence for {acid} on {platform}"))
    return best


def gate(requirements: list, scenarios: dict, evidences: dict, env: dict | None = None) -> dict:
    """A milestone gate passes only if every requirement is VERIFIED. Provisional evidence is reported, never counted."""
    failing, provisional = [], []
    for req in requirements:
        d = derive(req, scenarios, evidences, env)
        provisional += [(req.get("id"),) + p for p in d.provisional]
        if d.verification != "VERIFIED":
            failing.append({"requirement": req.get("id"), "verification": d.verification})
    return {"passed": not failing and bool(requirements), "failing": failing, "provisional": provisional}


def report_lines(req: dict, scenarios: dict, evidences: dict, env: dict | None = None) -> list:
    d = derive(req, scenarios, evidences, env)
    lines = [f"{req.get('id')}: verification {d.verification}, effective {d.effective_status}"]
    for acid, st in sorted(d.conditions.items()):
        lines.append(f"  {acid}: {st}")
    for eid, acid, pl, fp, unmet in d.provisional:
        lines.append(f"  provisionally supported (not counted): {eid} for {acid} on {pl}, fingerprint {str(fp)[:12]}")
    for f in d.findings:
        lines.append("  " + f.line())
    return lines
