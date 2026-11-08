"""IMP2-03 - aliases: historical labels attached to permanent IDs, each with a namespace and a documented source.

An alias never is the identity. ACTIVE / HISTORICAL need a literal occurrence of the label in the cited, hash-verified version of the source;
IMPLIED_BY_RANGE needs a literal range in the cited version and a label strictly between its ends (which therefore does NOT occur literally);
AMBIGUOUS never resolves to one record; REJECTED never resolves for linking. Nothing is merged, renamed or resolved by guesswork.
Codes: DE-02 malformed, DE-03 unknown source reference, DE-05 namespace / pattern / duplicate, DE-06 alias moved to another record,
DE-12 conditional field missing or misplaced, DE-13 contradiction with the cited source, AD-01 same string in two namespaces, AD-04 source not here.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, replace

from . import namespaces as ns_mod
from . import sources, store, textsource
from .findings import advisory, blocking, data_error

STATUSES = ("ACTIVE", "HISTORICAL", "AMBIGUOUS", "REJECTED", "IMPLIED_BY_RANGE")
USABLE = ("ACTIVE", "HISTORICAL", "IMPLIED_BY_RANGE")
_REQUIRED = {"namespace", "value", "status", "source"}
_OPTIONAL = {"range_source", "ambiguous_with", "note"}
_REF_FIELDS = {"source", "version", "anchor", "fragment", "quote"}


def _s(x):
    return isinstance(x, str)


def _ref_ok(r, exact=None):
    if not (isinstance(r, dict) and {"source", "version"} <= set(r) <= _REF_FIELDS and all(_s(v) and v for v in r.values())):
        return False
    return exact is None or set(r) == exact


def _sorted(findings):
    return sorted(findings, key=lambda f: (f.record, f.code, f.message))


def _aliases_of(obj):
    a = obj.get("aliases") if isinstance(obj, dict) else None
    return a if isinstance(a, list) else []


def _wellformed(a) -> bool:
    return isinstance(a, dict) and _s(a.get("namespace")) and _s(a.get("value")) and a.get("status") in STATUSES


def _remap(findings, rid, label):
    return [replace(f, record=rid, message=f"alias {label}: {f.message}") for f in findings]


def check_aliases(records, ns_obj, src_obj, roots) -> list:
    """records: {record id: record object}. ns_obj / src_obj: validated namespace and source catalogs."""
    out = []
    patterns = {}
    distinct = {}
    for n in ns_obj.get("namespaces", []) if isinstance(ns_obj, dict) else []:
        if isinstance(n, dict) and _s(n.get("key")) and _s(n.get("label_pattern")):
            try:
                patterns[n["key"]] = re.compile(n["label_pattern"])
            except re.error:
                continue
            distinct[n["key"]] = set(x for x in n.get("distinct_from", []) if _s(x))

    entries = []                                      # (rid, index, alias) with a usable core
    for rid in sorted(records):
        obj = records[rid]
        if not isinstance(obj, dict) or "aliases" not in obj:
            continue
        if not isinstance(obj["aliases"], list):
            out.append(data_error("DE-02", rid, "aliases must be a list"))
            continue
        for i, a in enumerate(obj["aliases"]):
            if _shape(a, rid, i, out):
                entries.append((rid, i, a))

    for rid, i, a in entries:
        _semantics(rid, i, a, patterns, src_obj, roots, out)
    _duplicates(entries, out)
    _same_string(entries, distinct, out)
    return _sorted(out)


def _shape(a, rid, i, out) -> bool:
    where = f"aliases[{i}]"

    def err(msg):
        out.append(data_error("DE-02", rid, f"{where}: {msg}"))

    if not isinstance(a, dict):
        err("an alias must be a JSON object")
        return False
    ok = True
    for f in sorted(_REQUIRED - set(a)):
        err(f"missing field {f!r}")
        ok = False
    for f in sorted(set(a) - _REQUIRED - _OPTIONAL):
        err(f"unknown field {f!r}")
        ok = False
    if "namespace" in a and not (_s(a["namespace"]) and a["namespace"]):
        err("namespace must be a non-empty string")
        ok = False
    if "value" in a and not (_s(a["value"]) and a["value"]):
        err("value must be a non-empty string")
        ok = False
    if "status" in a and a["status"] not in STATUSES:
        err(f"status {a['status']!r} is not one of {', '.join(STATUSES)}")
        ok = False
    if "source" in a and not _ref_ok(a["source"]):
        err("source must be {\"source\": key, \"version\": id} with optional anchor, fragment and quote (non-empty strings)")
        ok = False
    if "range_source" in a and not _ref_ok(a["range_source"], {"source", "version", "quote"}):
        err("range_source must be exactly {\"source\": key, \"version\": id, \"quote\": the literal range}")
        ok = False
    if "note" in a and not _s(a["note"]):
        err("note must be a string")
        ok = False
    if "ambiguous_with" in a:
        aw = a["ambiguous_with"]
        if not (isinstance(aw, list) and all(store.parse_id(x) is not None for x in aw)):
            err("ambiguous_with must be a list of record IDs")
            ok = False
    return ok


def _semantics(rid, i, a, patterns, src_obj, roots, out):
    ns, value, status = a["namespace"], a["value"], a["status"]
    label = f"{ns}:{value}"

    def add(code, msg, cls=data_error):
        out.append(cls(code, rid, f"alias {label}: {msg}"))

    if ns not in patterns:
        add("DE-05", f"unknown namespace {ns!r}")
        return
    if not patterns[ns].fullmatch(value):
        add("DE-05", f"the value does not match the pattern of the namespace {ns!r}")
        return
    if "range_source" in a and status != "IMPLIED_BY_RANGE":
        add("DE-12", "range_source is allowed only with the status IMPLIED_BY_RANGE")
    if "ambiguous_with" in a and status != "AMBIGUOUS":
        add("DE-12", "ambiguous_with is allowed only with the status AMBIGUOUS")
    src = a["source"]
    try:
        sources.find_version(src_obj, src["source"], src["version"])
    except sources.SourceLookupError as e:
        add("DE-03", f"source {e}")
        return
    if "quote" in src:
        out.extend(_remap(sources.check_quote(src_obj, roots, src), rid, label))
    if status in ("ACTIVE", "HISTORICAL"):
        _literal(rid, label, src, value, src_obj, roots, out, must_occur=True)
    elif status == "IMPLIED_BY_RANGE":
        _implied(rid, label, a, value, src_obj, roots, out)


def _literal(rid, label, ref, value, src_obj, roots, out, must_occur):
    """Literal occurrence of `value` in the verified bytes of ref's version. Returns the occurrences, or None if it could not be checked."""
    try:
        occ = sources.find_label_in(src_obj, roots, ref["source"], ref["version"], value)
    except sources.SourceUnavailable as e:
        out.append(advisory("AD-04", rid, f"alias {label}: source file not available in this environment ({e}); the literal occurrence was not checked"))
        return None
    except sources.SourceMismatch as e:
        out.append(data_error("DE-13", rid, f"alias {label}: the label cannot be checked, {e}"))
        return None
    except sources.SourceLocationError as e:
        out.append(data_error("DE-02", rid, f"alias {label}: {e}"))
        return None
    except textsource.SourceTextError as e:
        out.append(data_error("DE-13", rid, f"alias {label}: the pinned bytes are not UTF-8 text ({e})"))
        return None
    if must_occur and not occ:
        out.append(data_error("DE-13", rid, f"alias {label}: the label does not occur literally in {ref['source']}/{ref['version']}"))
    return occ


def _implied(rid, label, a, value, src_obj, roots, out):
    rs = a.get("range_source")
    if rs is None:
        out.append(data_error("DE-12", rid, f"alias {label}: IMPLIED_BY_RANGE needs range_source (the literal range in a pinned source)"))
        return
    try:
        sources.find_version(src_obj, rs["source"], rs["version"])
    except sources.SourceLookupError as e:
        out.append(data_error("DE-03", rid, f"alias {label}: range_source {e}"))
        return
    qf = sources.check_quote(src_obj, roots, rs)
    out.extend(_remap(qf, rid, label))
    if textsource.parse_range(rs["quote"]) is None:
        out.append(data_error("DE-13", rid, f"alias {label}: {rs['quote']!r} is not a supported range (PREFIXn, a dash, PREFIXm with n < m)"))
    elif not textsource.label_between(value, rs["quote"]):
        out.append(data_error("DE-13", rid, f"alias {label}: the label does not lie strictly between the ends of the range {rs['quote']!r}"))
    if not qf:                                                # the range is verified, so the file is here and unchanged
        occ = _literal(rid, label, rs, value, src_obj, roots, out, must_occur=False)
        if occ:
            out.append(data_error("DE-13", rid, f"alias {label}: the label occurs literally in {rs['source']}/{rs['version']}; "
                                                f"it is then ACTIVE or HISTORICAL, not implied by a range"))


def _duplicates(entries, out):
    groups = {}
    for rid, i, a in entries:
        groups.setdefault((a["namespace"], a["value"]), []).append((rid, i, a))
    for (ns, value), g in sorted(groups.items()):
        if len(g) == 1:
            rid, i, a = g[0]
            if a["status"] == "AMBIGUOUS" and a.get("ambiguous_with"):
                out.append(data_error("DE-05", rid, f"alias {ns}:{value}: ambiguous_with names records that do not carry this alias"))
            continue
        ids = [rid for rid, _, _ in g]
        all_amb = all(a["status"] == "AMBIGUOUS" for _, _, a in g)
        for rid, i, a in g:
            if not all_amb or len(set(ids)) != len(ids):
                out.append(data_error("DE-05", rid, f"alias {ns}:{value}: the same (namespace, value) is used {len(g)} times "
                                                    f"({', '.join(sorted(ids))}); only AMBIGUOUS aliases naming each other may share it"))
            elif set(a.get("ambiguous_with", [])) != set(ids) - {rid}:
                out.append(data_error("DE-05", rid, f"alias {ns}:{value}: ambiguous_with must list exactly the other records carrying it "
                                                    f"({', '.join(sorted(set(ids) - {rid}))})"))


def _same_string(entries, distinct, out):
    by_value = {}
    for rid, i, a in entries:
        by_value.setdefault(a["value"], set()).add(a["namespace"])
    for value, spaces in sorted(by_value.items()):
        known = sorted(s for s in spaces if s in distinct)
        for x in range(len(known)):
            for y in range(x + 1, len(known)):
                a, b = known[x], known[y]
                if b not in distinct[a] and a not in distinct[b]:
                    out.append(advisory("AD-01", value, f"the string {value!r} is used in the namespaces {a} and {b}, which do not declare distinct_from"))


# --- resolution ------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Resolution:
    status: str          # an alias status, UNKNOWN, or AMBIGUOUS when several records carry it
    targets: tuple
    usable: bool         # may a link be built on it? (never for REJECTED, AMBIGUOUS, UNKNOWN)


def build_index(records) -> dict:
    index = {}
    for rid in sorted(records):
        for a in _aliases_of(records[rid]):
            if _wellformed(a):
                index.setdefault((a["namespace"], a["value"]), []).append((rid, a))
    return index


def resolve(index, namespace, value) -> Resolution:
    found = index.get((namespace, value), [])
    if not found:
        return Resolution("UNKNOWN", (), False)
    if len(found) > 1:
        return Resolution("AMBIGUOUS", tuple(sorted(rid for rid, _ in found)), False)
    rid, a = found[0]
    return Resolution(a["status"], (rid,), a["status"] in USABLE)


# --- moves between base and head -----------------------------------------------------------------------------------------------------
def alias_map(records) -> dict:
    m = {}
    for rid in records:
        for a in _aliases_of(records[rid]):
            if _wellformed(a):
                m.setdefault((a["namespace"], a["value"]), set()).add(rid)
    return m


def check_moves(base_map, head_map) -> list:
    out = []
    for key in sorted(base_map):
        b, h = base_map[key], head_map.get(key, set())
        if b and h and (b - h) and (h - b):
            out.append(data_error("DE-06", f"{key[0]}:{key[1]}", f"alias moved from {', '.join(sorted(b - h))} to {', '.join(sorted(h - b))}; "
                                                                 f"an alias stays with the record it was given to"))
    return _sorted(out)


def check_moves_against_base(root, head_records, base) -> list:
    return check_moves(alias_map(store.base_objects(root, base)), alias_map(head_records))


# --- command line -----------------------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clxreg.aliases")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--root", required=True)
    c.add_argument("--namespaces", required=True)
    c.add_argument("--catalog", required=True)
    c.add_argument("--source-root", action="append")
    c.add_argument("--base")
    a = ap.parse_args(argv)
    try:
        roots = sources.parse_roots(a.source_root)
        st = store.load(a.root)
        findings = list(st.findings)
        ns_obj, f1 = ns_mod.load_namespaces(a.namespaces)
        src_obj, f2 = sources.load_catalog(a.catalog)
        cat = f1 + f2
        if ns_obj is not None and src_obj is not None:
            cat += sources.validate_catalog(src_obj)
            cat += ns_mod.validate_namespaces(ns_obj, src_obj)
        findings += cat
        heads = {r.id: r.obj for r in st.records.values()}
        if not blocking(cat):
            findings += ns_mod.check_authorities(ns_obj, src_obj, roots)
            findings += check_aliases(heads, ns_obj, src_obj, roots)
        if a.base is not None:
            findings += check_moves_against_base(a.root, heads, a.base)
    except (sources.SourceError, store.StoreError) as e:
        print(f"aliases: {e}", file=sys.stderr)
        return 3
    for f in findings:
        print(f.line())
    n = sum(len(_aliases_of(o)) for o in heads.values())
    print(f"aliases: {'FAIL' if blocking(findings) else 'OK'} (records: {len(heads)}, aliases: {n}, findings: {len(findings)})")
    return 1 if blocking(findings) else 0


if __name__ == "__main__":
    sys.exit(main())
