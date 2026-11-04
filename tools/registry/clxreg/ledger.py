"""IMP2-05 - the import ledger: a repeatable, read-only inventory of what the sources contain, with a disposition for every occurrence.

Invariants (owner, S1): the original source is kept (identity + SHA-256 of the pinned bytes); every occurrence has an exact location (unit, column,
length) and its literal, unnormalised text; the historical namespace and the original label are kept; every entry has an explicit disposition and no
meaning is guessed; original states, references and result phrases are recorded (IMP2-07a); the import is deterministic; nothing is dropped,
merged or expanded silently (a match inside a longer one is kept inside it, a range stays a range, a label of two namespaces stays ambiguous);
what could not be processed (missing, unsupported, excluded, changed) is stated, never skipped.
Exit codes of `build`: 0 complete, 1 problems (changed source, bad mapping), 2 incomplete (missing / unsupported source), 3 inputs unusable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import __version__, canon, literals, namespaces, patterns, sources, store, units
from .findings import advisory, blocking, data_error

SCHEMA = "clx.ledger/1"
RUN_SCHEMA = "clx.ledger-run/1"
MAPPING_SCHEMA = "clx.mapping/1"
DISPOSITIONS = ("MIGRATED_AS_ALIAS", "NOT_MIGRATED", "AMBIGUOUS", "RANGE_NOT_EXPANDED", "UNCLASSIFIED_LABEL", "UNSUPPORTED", "SOURCE_MISSING", "EXCLUDED")
CLASSES = ("LABEL", "RANGE", "UNCLASSIFIED", "STATE_WORD", "REFERENCE", "RESULT_PHRASE", "SOURCE")
_CLASS_ORDER = {c: i for i, c in enumerate(CLASSES)}
_SOURCE_DISPOSITIONS = ("UNSUPPORTED", "SOURCE_MISSING", "EXCLUDED")
_LITERAL_CLASSES = ("STATE_WORD", "REFERENCE", "RESULT_PHRASE")
_ENTRY_KEY = ("source", "version", "unit", "column", "length", "class", "text")
_DIFF_FIELDS = ("disposition", "namespace", "candidates", "meanings", "record", "status", "reason", "ends", "contained", "patterns", "decision")


class LedgerInputError(RuntimeError):
    """The inputs cannot be used (invalid catalog, run or mapping); no ledger is produced."""


def _s(x):
    return isinstance(x, str) and x != ""


# --- inputs ----------------------------------------------------------------------------------------------------------------------
def validate_run(run, src_cat) -> list:
    out = []

    def err(code, rec, msg):
        out.append(data_error(code, rec, msg))

    if not isinstance(run, dict):
        return [data_error("DE-02", "run", "the run configuration must be a JSON object")]
    for k in sorted(set(run) - {"schema", "include", "excluded"}):
        err("DE-02", "run", f"unknown field {k!r}")
    if run.get("schema") != RUN_SCHEMA:
        err("DE-02", "run", f"schema must be {RUN_SCHEMA!r}, found {run.get('schema')!r}")
    inc = run.get("include")
    if not isinstance(inc, list) or not inc:
        err("DE-02", "run", "'include' must be a non-empty list of {source, version}")
        inc = []
    exc = run.get("excluded", [])
    if not isinstance(exc, list):
        err("DE-02", "run", "'excluded' must be a list")
        exc = []

    def ref_ok(item, fields):
        return isinstance(item, dict) and set(item) == fields and all(_s(item[f]) for f in fields)

    seen = {}
    for i, item in enumerate(inc):
        if not ref_ok(item, {"source", "version"}):
            err("DE-02", f"run:include[{i}]", "an included source must be exactly {source, version} (non-empty strings)")
            continue
        k = (item["source"], item["version"])
        seen[k] = seen.get(k, 0) + 1
        _resolve(src_cat, k, f"run:include[{i}]", err)
    for i, item in enumerate(exc):
        if not ref_ok(item, {"source", "version", "reason", "decision"}):
            err("DE-02", f"run:excluded[{i}]", "an exclusion must be exactly {source, version, reason, decision} (non-empty strings): no exclusion without a reason and a decision")
            continue
        k = (item["source"], item["version"])
        seen[k] = seen.get(k, 0) + 1
        _resolve(src_cat, k, f"run:excluded[{i}]", err)
    for k, n in sorted(seen.items()):
        if n > 1:
            err("DE-01", f"run:{k[0]}/{k[1]}", f"the source version is listed {n} times (included or excluded): a source is never imported twice")
    return sorted(out, key=lambda f: (f.record, f.code, f.message))


def _resolve(src_cat, k, rec, err):
    try:
        sources.find_version(src_cat, k[0], k[1])
    except sources.SourceLookupError:
        err("DE-03", rec, f"{k[0]}/{k[1]} is not in the source catalog")


def validate_mapping(mapping, ns_obj) -> list:
    out = []

    def err(code, rec, msg):
        out.append(data_error(code, rec, msg))

    if not isinstance(mapping, dict):
        return [data_error("DE-02", "mapping", "the mapping must be a JSON object")]
    for k in sorted(set(mapping) - {"schema", "tokens"}):
        err("DE-02", "mapping", f"unknown field {k!r}")
    if mapping.get("schema") != MAPPING_SCHEMA:
        err("DE-02", "mapping", f"schema must be {MAPPING_SCHEMA!r}, found {mapping.get('schema')!r}")
    tokens = mapping.get("tokens")
    if not isinstance(tokens, dict):
        err("DE-02", "mapping", "'tokens' must be an object {\"namespace:value\": decision}")
        return sorted(out, key=lambda f: (f.record, f.code, f.message))
    compiled = dict(patterns.compile_namespaces(ns_obj))
    for key in sorted(tokens):
        rec = f"mapping:{key}"
        ns, colon, value = key.partition(":")
        if not colon or not ns or not value:
            err("DE-02", rec, "the key must be namespace:value")
        elif ns not in compiled:
            err("DE-05", rec, f"unknown namespace {ns!r}")
        elif not compiled[ns].fullmatch(value):
            err("DE-05", rec, f"the value does not match the pattern of the namespace {ns!r}")
        d = tokens[key]
        if not isinstance(d, dict):
            err("DE-02", rec, "a decision must be a JSON object")
            continue
        for f in sorted(set(d) - {"disposition", "record", "status", "reason"}):
            err("DE-02", rec, f"unknown field {f!r}")
        if not _s(d.get("reason")):
            err("DE-02", rec, "a decision needs a non-empty reason")
        disp = d.get("disposition")
        if disp == "MIGRATED_AS_ALIAS":
            pid = store.parse_id(d.get("record"))
            if pid is None or pid[0] not in store.STORED_TYPES:
                err("DE-02", rec, "MIGRATED_AS_ALIAS needs record: the ID of a record of the store (CLX-REQ|SCN|EVD|MIL-nnnn)")
            if d.get("status") not in ("ACTIVE", "HISTORICAL"):
                err("DE-02", rec, "MIGRATED_AS_ALIAS needs an explicit status, ACTIVE or HISTORICAL (the tool does not decide)")
        elif disp == "NOT_MIGRATED":
            for f in ("record", "status"):
                if f in d:
                    err("DE-02", rec, f"NOT_MIGRATED must not carry {f}")
        else:
            err("DE-02", rec, "disposition must be MIGRATED_AS_ALIAS or NOT_MIGRATED (ambiguous labels and ranges cannot be mapped)")
    return sorted(out, key=lambda f: (f.record, f.code, f.message))


# --- build ---------------------------------------------------------------------------------------------------------------------------
def build_ledger(run, src_cat, ns_obj, amb_obj, mapping, roots) -> dict:
    findings = sources.validate_catalog(src_cat)
    if not blocking(findings):
        findings += namespaces.validate_namespaces(ns_obj, src_cat)
        if not blocking(findings):
            findings += validate_run(run, src_cat)
            if amb_obj is not None:
                findings += patterns.validate_ambiguity(amb_obj, ns_obj)
            if mapping is not None:
                findings += validate_mapping(mapping, ns_obj)
    if blocking(findings):
        raise LedgerInputError("\n".join(f.line() for f in findings if f.cls == "DATA_ERROR"))
    compiled = patterns.compile_namespaces(ns_obj)
    tokens = mapping["tokens"] if mapping else {}
    st = {"seen": set(), "ambiguous": set()}
    entries, srcs, problems = [], [], []

    def source_entry(ref, sha, disposition, reason, **extra):
        e = {"class": "SOURCE", "disposition": disposition, "source": ref[0], "version": ref[1], "sha256": sha, "reason": reason}
        e.update(extra)
        return e

    for item in run["include"]:
        ref = (item["source"], item["version"])
        v = sources.find_version(src_cat, *ref)
        info = {"source": ref[0], "version": ref[1], "sha256": v["sha256"]}
        try:
            data = sources.read_verified(src_cat, roots, *ref)
        except sources.SourceUnavailable as e:
            entries.append(source_entry(ref, v["sha256"], "SOURCE_MISSING", str(e)))
            srcs.append(dict(info, status="MISSING"))
            continue
        except (sources.SourceMismatch, sources.SourceLocationError) as e:
            problems.append(f"{ref[0]}/{ref[1]}: {e}")
            srcs.append(dict(info, status="PROBLEM"))
            continue
        try:
            us = units.read_units(units.suffix_of(v["location"]["path"]), data)
        except units.UnsupportedSource as e:
            entries.append(source_entry(ref, v["sha256"], "UNSUPPORTED", str(e)))
            srcs.append(dict(info, status="UNSUPPORTED"))
            continue
        mine = []
        for u in us:
            mine.extend(_scan_unit(u, ref, v["sha256"], compiled, amb_obj, tokens, st))
        try:
            again = sources.read_verified(src_cat, roots, *ref)
        except sources.SourceError as e:
            again, why = None, str(e)
        else:
            why = "the bytes differ from the first read"
        if again != data:
            problems.append(f"{ref[0]}/{ref[1]}: the source changed during the import ({why})")
            srcs.append(dict(info, status="PROBLEM"))
            continue
        entries.extend(mine)
        srcs.append(dict(info, status="PROCESSED", **_coverage(us, {e["unit"] for e in mine})))
    for item in run.get("excluded", []):
        ref = (item["source"], item["version"])
        v = sources.find_version(src_cat, *ref)
        entries.append(source_entry(ref, v["sha256"], "EXCLUDED", item["reason"], decision=item["decision"]))
        srcs.append({"source": ref[0], "version": ref[1], "sha256": v["sha256"], "status": "EXCLUDED"})

    for key in sorted(tokens):
        if key in st["ambiguous"]:
            problems.append(f"mapping {key}: the label is ambiguous (several namespaces or an ambiguity rule); ambiguous labels are never mapped by batch")
        elif key not in st["seen"]:
            problems.append(f"mapping {key}: matches no occurrence in the imported sources (a label that only lies inside a range is not an occurrence)")

    for n, e in enumerate(entries, 1):
        e["n"] = n
    by_disp, by_cls = {}, {}
    for e in entries:
        by_disp[e["disposition"]] = by_disp.get(e["disposition"], 0) + 1
        by_cls[e["class"]] = by_cls.get(e["class"], 0) + 1
    inputs = {"tool": __version__, "run_digest": canon.digest(run), "catalog_digest": canon.digest(src_cat), "namespaces_digest": canon.digest(ns_obj)}
    if amb_obj is not None:
        inputs["ambiguity_digest"] = canon.digest(amb_obj)
    if mapping is not None:
        inputs["mapping_digest"] = canon.digest(mapping)
    problems.sort()
    return {"schema": SCHEMA, "inputs": inputs, "sources": srcs, "entries": entries,
            "summary": {"entries": len(entries), "sources": len(srcs), "dispositions": by_disp, "classes": by_cls},
            "problems": problems, "complete": not problems and all(s["status"] in ("PROCESSED", "EXCLUDED") for s in srcs)}


def _scan_unit(u, ref, sha, compiled, amb_obj, tokens, st) -> list:
    items = [(m.start, m.end, _CLASS_ORDER[m.cls], m) for m in patterns.scan_text(u.text, compiled)]
    items += [(m.start, m.end, _CLASS_ORDER[m.cls], m) for m in literals.scan_literals(u.text)]
    items.sort(key=lambda i: (i[0], i[1], i[2]))
    out = []
    for start, end, _, m in items:
        e = {"source": ref[0], "version": ref[1], "sha256": sha, "unit": u.id, "column": start + 1, "length": end - start, "class": m.cls, "text": m.text}
        if u.line is not None:
            e["line"] = u.line
        if m.cls in _LITERAL_CLASSES:
            e.update(disposition="UNCLASSIFIED_LABEL", patterns=list(m.patterns), reason="recorded literally, not interpreted (IMP2-07a)")
        elif m.cls == "RANGE":
            e.update(disposition="RANGE_NOT_EXPANDED", ends=list(m.ends), reason="range of labels; the members between the ends are not asserted to exist and are not expanded")
        elif m.cls == "UNCLASSIFIED":
            e.update(disposition="UNCLASSIFIED_LABEL", reason="label-like token without a known namespace; needs an inventory decision (it may be external, e.g. a tool rule id)")
        else:
            _label(e, m, amb_obj, tokens, st)
        if getattr(m, "contained", ()):
            e["contained"] = [{"text": c.text, "column": c.start + 1, "class": c.cls, "namespaces": list(c.namespaces)} for c in m.contained]
        out.append(e)
    return out


def _label(e, m, amb_obj, tokens, st):
    ns = list(m.namespaces)
    meanings = patterns.ambiguity_meanings(amb_obj, ns[0], m.text) if len(ns) == 1 else None
    if len(ns) > 1 or meanings:
        e.update(disposition="AMBIGUOUS", candidates=ns, reason="the label has several meanings; the tool does not choose")
        if meanings:
            e["meanings"] = meanings
        for n in ns:
            st["ambiguous"].add(f"{n}:{m.text}")
        return
    key = f"{ns[0]}:{m.text}"
    st["seen"].add(key)
    e["namespace"] = ns[0]
    d = tokens.get(key)
    if d is None:
        e.update(disposition="NOT_MIGRATED", reason="no mapping yet (reported, not dropped)")
    else:
        e.update(disposition=d["disposition"], reason=d["reason"])
        if d["disposition"] == "MIGRATED_AS_ALIAS":
            e.update(record=d["record"], status=d["status"])


def _coverage(us, with_entries) -> dict:
    nonblank = [u for u in us if u.text.strip()]
    uncovered = [u for u in nonblank if u.id not in with_entries]
    d = {"units": len(us), "blank_units": len(us) - len(nonblank), "units_with_entries": len([u for u in us if u.id in with_entries]),
         "uncovered_count": len(uncovered), "uncovered_sha256": hashlib.sha256("\n".join(u.id for u in uncovered).encode("utf-8")).hexdigest()}
    if all(u.line is not None for u in us):
        ranges = []
        for u in uncovered:
            if ranges and ranges[-1][1] == u.line - 1:
                ranges[-1][1] = u.line
            else:
                ranges.append([u.line, u.line])
        d["uncovered_line_ranges"] = ranges
    return d


# --- checks on a ledger ------------------------------------------------------------------------------------------------------------------
def validate_ledger(led) -> list:
    out = []

    def err(code, rec, msg):
        out.append(data_error(code, rec, msg))

    if not isinstance(led, dict):
        return [data_error("DE-02", "ledger", "a ledger must be a JSON object")]
    if led.get("schema") != SCHEMA:
        err("DE-02", "ledger", f"schema must be {SCHEMA!r}")
    entries = led.get("entries")
    if not isinstance(entries, list):
        err("DE-02", "ledger", "'entries' must be a list")
        return sorted(out, key=lambda f: (f.record, f.code, f.message))
    seen, by_disp, by_cls = {}, {}, {}
    for i, e in enumerate(entries, 1):
        rec = f"ledger:#{i}"
        if not isinstance(e, dict):
            err("DE-02", rec, "an entry must be a JSON object")
            continue
        if e.get("n") != i:
            err("DE-02", rec, f"n is {e.get('n')!r}, expected {i}: entries are numbered without gaps")
        d, c = e.get("disposition"), e.get("class")
        if d not in DISPOSITIONS:
            err("DE-02", rec, f"disposition {d!r} is not one of the closed set")
        if c not in CLASSES:
            err("DE-02", rec, f"class {c!r} is not one of the closed set")
        by_disp[d] = by_disp.get(d, 0) + 1
        by_cls[c] = by_cls.get(c, 0) + 1
        for f in ("source", "version", "sha256", "reason"):
            if not _s(e.get(f)):
                err("DE-02", rec, f"missing or empty {f}")
        if c == "SOURCE":
            if d not in _SOURCE_DISPOSITIONS:
                err("DE-02", rec, "a source-level entry is UNSUPPORTED, SOURCE_MISSING or EXCLUDED")
            if d == "EXCLUDED" and not _s(e.get("decision")):
                err("DE-02", rec, "EXCLUDED needs the decision that excluded the source")
            continue
        if d in _SOURCE_DISPOSITIONS:
            err("DE-02", rec, f"{d} belongs to a source-level entry")
        text = e.get("text")
        if not (_s(text) and e.get("length") == len(text)):
            err("DE-02", rec, "text must be non-empty and length must equal its length")
        if not (type(e.get("column")) is int and e["column"] >= 1 and _s(e.get("unit"))):
            err("DE-02", rec, "an entry needs unit and column >= 1")
        key = tuple(json.dumps(e.get(k), sort_keys=True) for k in _ENTRY_KEY)
        if key in seen:
            err("DE-01", rec, f"the same occurrence is recorded twice (also #{seen[key]})")
        seen.setdefault(key, i)
        mig = d == "MIGRATED_AS_ALIAS"
        if ("record" in e or "status" in e) and not mig:
            err("DE-02", rec, "record and status belong only to MIGRATED_AS_ALIAS: no identity is attached to anything else")
        if mig and not (store.parse_id(e.get("record")) and e.get("status") in ("ACTIVE", "HISTORICAL")):
            err("DE-02", rec, "MIGRATED_AS_ALIAS needs record and an explicit status")
        if d == "AMBIGUOUS":
            if not (isinstance(e.get("candidates"), list) and e["candidates"]):
                err("DE-02", rec, "AMBIGUOUS needs its candidates")
            if "namespace" in e:
                err("DE-02", rec, "an ambiguous label has no single namespace")
        elif c == "LABEL" and d != "AMBIGUOUS" and not _s(e.get("namespace")):
            err("DE-02", rec, "a label that is not ambiguous keeps its historical namespace")
        want = {"RANGE": "RANGE_NOT_EXPANDED", "UNCLASSIFIED": "UNCLASSIFIED_LABEL", "STATE_WORD": "UNCLASSIFIED_LABEL", "REFERENCE": "UNCLASSIFIED_LABEL",
                "RESULT_PHRASE": "UNCLASSIFIED_LABEL"}.get(c)
        if want and d != want:
            err("DE-02", rec, f"class {c} has the disposition {want}")
        if c == "LABEL" and d in ("RANGE_NOT_EXPANDED", "UNCLASSIFIED_LABEL"):
            err("DE-02", rec, f"a label cannot have the disposition {d}")
    summary = led.get("summary")
    n_sources = len(led["sources"]) if isinstance(led.get("sources"), list) else None
    if summary != {"entries": len(entries), "sources": n_sources, "dispositions": by_disp, "classes": by_cls}:
        err("DE-02", "ledger", "the summary does not match the entries")
    if led.get("problems") and led.get("complete") is not False:
        err("DE-02", "ledger", "a ledger with problems cannot be complete")
    return sorted(out, key=lambda f: (f.record, f.code, f.message))


def verify_ledger(led, src_cat, roots) -> list:
    """Re-locate every entry in the verified bytes of its source; re-derive the coverage map."""
    out = []
    problems = led.get("problems") if isinstance(led, dict) else None
    if problems:
        out.append(data_error("DE-13", "ledger", f"the ledger itself records {len(problems)} problem(s)"))
    by_src = {}
    for e in led.get("entries", []):
        by_src.setdefault((e.get("source"), e.get("version")), []).append(e)
    for s in led.get("sources", []):
        ref = (s["source"], s["version"])
        rec = f"ledger:{ref[0]}/{ref[1]}"
        try:
            pinned = sources.find_version(src_cat, *ref)["sha256"]
        except sources.SourceLookupError:
            out.append(data_error("DE-03", rec, "the source is not in the catalog"))
            continue
        if s["sha256"] != pinned:
            out.append(data_error("DE-13", rec, "the ledger names another hash than the catalog pins"))
            continue
        if s["status"] != "PROCESSED":
            continue
        try:
            data = sources.read_verified(src_cat, roots, *ref)
            us = units.read_units(units.suffix_of(sources.find_version(src_cat, *ref)["location"]["path"]), data)
        except sources.SourceUnavailable as e:
            out.append(advisory("AD-04", rec, f"source not available in this environment ({e}); its entries were not re-located"))
            continue
        except (sources.SourceMismatch, sources.SourceLocationError, units.UnsupportedSource) as e:
            out.append(data_error("DE-13", rec, str(e)))
            continue
        by_id = {u.id: u for u in us}
        for e in by_src.get(ref, []):
            erec = f"ledger:#{e.get('n')}"
            u = by_id.get(e.get("unit"))
            if e.get("sha256") != pinned:
                out.append(data_error("DE-13", erec, "the entry names another source hash than the pinned one"))
            elif u is None:
                out.append(data_error("DE-13", erec, f"unit {e.get('unit')!r} does not exist in the source"))
            elif e.get("line") != u.line:
                out.append(data_error("DE-13", erec, f"the entry says line {e.get('line')!r}, the unit is at {u.line!r}"))
            elif u.text[e["column"] - 1:e["column"] - 1 + e["length"]] != e["text"] or len(e["text"]) != e["length"]:
                out.append(data_error("DE-13", erec, "the text is not at the stated location of the source"))
            else:
                for c in e.get("contained", []):
                    if u.text[c["column"] - 1:c["column"] - 1 + len(c["text"])] != c["text"]:
                        out.append(data_error("DE-13", erec, f"contained {c['text']!r} is not at its stated location"))
        expect = _coverage(us, {e.get("unit") for e in by_src.get(ref, [])})
        for k, v in expect.items():
            if s.get(k) != v:
                out.append(data_error("DE-13", rec, f"coverage {k} is {s.get(k)!r}, re-derived {v!r}"))
    return sorted(out, key=lambda f: (f.record, f.code, f.message))


def compare_with_rebuild(led, run, src_cat, ns_obj, amb_obj, mapping, roots) -> list:
    fresh = build_ledger(run, src_cat, ns_obj, amb_obj, mapping, roots)
    if canon.dumps(fresh) != canon.dumps(led):
        return [data_error("DE-13", "ledger", "the ledger differs from a fresh import of the same inputs (an entry was added, dropped or changed)")]
    return []


def diff_ledgers(a, b) -> dict:
    def index(led):
        return {tuple(json.dumps(e.get(k), sort_keys=True) for k in _ENTRY_KEY): e for e in led.get("entries", [])}

    ia, ib = index(a), index(b)
    added = [ib[k] for k in sorted(set(ib) - set(ia))]
    removed = [ia[k] for k in sorted(set(ia) - set(ib))]
    changed = []
    for k in sorted(set(ia) & set(ib)):
        x, y = ia[k], ib[k]
        diff = [f for f in _DIFF_FIELDS if x.get(f) != y.get(f)]
        if diff:
            changed.append({**{f: x.get(f) for f in _ENTRY_KEY}, "before": {f: x.get(f) for f in diff if f in x}, "after": {f: y.get(f) for f in diff if f in y}})
    sa = {(s["source"], s["version"]): (s["sha256"], s["status"]) for s in a.get("sources", [])}
    sb = {(s["source"], s["version"]): (s["sha256"], s["status"]) for s in b.get("sources", [])}
    return {"added": added, "removed": removed, "changed": changed, "sources_changed": [list(k) for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)]}


# --- command line -----------------------------------------------------------------------------------------------------------------------
def load_input(path, name):
    obj, f = sources.load_canonical(path, name)
    if obj is None or f:
        raise LedgerInputError("\n".join(x.line() for x in f))
    return obj


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clxreg.ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    v = sub.add_parser("verify")
    for p in (b, v):
        p.add_argument("--catalog", required=True)
        p.add_argument("--root", action="append")
    b.add_argument("--run", required=True)
    b.add_argument("--namespaces", required=True)
    b.add_argument("--ambiguity")
    b.add_argument("--mapping")
    b.add_argument("--out", required=True)
    v.add_argument("--ledger", required=True)
    v.add_argument("--run")
    v.add_argument("--namespaces")
    v.add_argument("--ambiguity")
    v.add_argument("--mapping")
    d = sub.add_parser("diff")
    d.add_argument("a")
    d.add_argument("b")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "diff":
            r = diff_ledgers(load_input(a.a, "ledger"), load_input(a.b, "ledger"))
            print(f"added: {len(r['added'])}, removed: {len(r['removed'])}, changed: {len(r['changed'])}, sources changed: {len(r['sources_changed'])}")
            for k in ("added", "removed"):
                for e in r[k]:
                    print(f"{k:<8} {e['source']}/{e['version']} {e['unit']} col {e['column']} {e['text']!r}")
            for c in r["changed"]:
                print(f"changed  {c['source']}/{c['version']} {c['unit']} col {c['column']} {c['text']!r}: {c['before']} -> {c['after']}")
            if not (r["added"] or r["removed"] or r["changed"] or r["sources_changed"]):
                print("no difference")
                return 0
            return 1
        roots = sources.parse_roots(a.root)
        catalog = load_input(a.catalog, "sources")
        if a.cmd == "verify":
            led = load_input(a.ledger, "ledger")
            findings = validate_ledger(led) + verify_ledger(led, catalog, roots)
            if a.run:
                if not a.namespaces:
                    raise LedgerInputError("--run needs --namespaces to rebuild")
                findings += compare_with_rebuild(led, load_input(a.run, "run"), catalog, load_input(a.namespaces, "namespaces"),
                                                 load_input(a.ambiguity, "ambiguity") if a.ambiguity else None, load_input(a.mapping, "mapping") if a.mapping else None, roots)
            for f in findings:
                print(f.line())
            print(f"verify: {'FAIL' if blocking(findings) else 'OK'} ({len(findings)} findings)")
            return 1 if blocking(findings) else 0
        led = build_ledger(load_input(a.run, "run"), catalog, load_input(a.namespaces, "namespaces"), load_input(a.ambiguity, "ambiguity") if a.ambiguity else None,
                           load_input(a.mapping, "mapping") if a.mapping else None, roots)
        try:
            canon.write_record(Path(a.out), led)
        except FileExistsError:
            print(f"ledger: refusing to overwrite {a.out}: it exists", file=sys.stderr)
            return 3
    except (LedgerInputError, sources.SourceError, OSError) as e:
        print(f"ledger: {e}", file=sys.stderr)
        return 3
    text = Path(a.out).read_bytes()
    print(f"ledger: {a.out} sha256 {hashlib.sha256(text).hexdigest()}")
    print(f"entries: {led['summary']['entries']} dispositions: {json.dumps(led['summary']['dispositions'], sort_keys=True)}")
    for p in led["problems"]:
        print(f"PROBLEM: {p}")
    for s in led["sources"]:
        if s["status"] not in ("PROCESSED", "EXCLUDED"):
            print(f"source {s['source']}/{s['version']}: {s['status']}")
    if led["problems"]:
        print("status: PROBLEMS")
        return 1
    if not led["complete"]:
        print("status: INCOMPLETE (a source is missing or unsupported)")
        return 2
    print("status: complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
