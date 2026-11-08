"""IMP2-08 - dry-run generator of candidate aliases from a ledger and an approved mapping.

Writes into a NEW directory only (never into the registry, a source root or an existing directory). It maps nothing that is ambiguous, nothing that
lies only inside a range, and nothing that is not in the ledger: such a mapping entry is an error, not a warning. The difference between the
ledger built without and with the mapping must be exactly the mapping. Every candidate alias is checked with the alias rules against the real
store before anything is written, carries its origin (source, version, anchor, literal quote) and lists every occurrence the ledger found.
Deciding who resolves an ambiguous label (TD-9) is not done here: the generator simply does not let it through.
Exit codes of `generate`: 0 written, 3 refused (nothing written).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from . import aliases, canon, ledger, sources, store, units
from .findings import blocking, data_error

CANDIDATE_SCHEMA = "clx.alias-candidates/1"
MANIFEST_SCHEMA = "clx.candidates-manifest/1"
_ENTRY_KEY = ("source", "version", "unit", "column", "length", "class", "text")
_MAPPING_FIELDS = {"disposition", "reason", "record", "status"}


class CandidateError(RuntimeError):
    """The generation is refused; nothing has been written."""


def _key(e):
    return tuple(json.dumps(e.get(k), sort_keys=True) for k in _ENTRY_KEY)


def check_mapping_diff(diff, mapping, after_entries) -> list:
    """The difference between the ledger without and with the mapping must be exactly the mapping."""
    out = []
    tokens = mapping["tokens"]
    if diff["added"] or diff["removed"]:
        out.append(data_error("DE-13", "ledger", f"the mapping added {len(diff['added'])} and removed {len(diff['removed'])} entries; it may only change dispositions"))
    for s in diff["sources_changed"]:
        out.append(data_error("DE-13", "ledger", f"source {s[0]}/{s[1]} differs between the two imports"))
    index = {_key(e): e for e in after_entries}
    touched = set()
    for c in diff["changed"]:
        e = index.get(tuple(json.dumps(c.get(k), sort_keys=True) for k in _ENTRY_KEY))
        label = f"{c.get('unit')} {c.get('text')!r}"
        if e is None or e.get("class") != "LABEL" or "namespace" not in e:
            out.append(data_error("DE-13", "ledger", f"an entry that is not a mappable label changed: {label}"))
            continue
        k = f"{e['namespace']}:{e['text']}"
        if k not in tokens:
            out.append(data_error("DE-13", f"mapping:{k}", f"an entry changed although the mapping does not name it: {label}"))
        if (set(c["before"]) | set(c["after"])) - _MAPPING_FIELDS:
            out.append(data_error("DE-13", f"mapping:{k}", f"fields other than the decision changed: {label}"))
        touched.add(k)
    for k in sorted(set(tokens) - touched):
        out.append(data_error("DE-13", f"mapping:{k}", f"the mapping entry {k} changed no entry of the ledger"))
    return sorted(out, key=lambda f: (f.record, f.code, f.message))


def generate(run, src_cat, ns_obj, amb_obj, mapping, roots, store_root, out_dir) -> dict:
    if not isinstance(mapping, dict):
        raise CandidateError("an approved mapping is required")
    out = Path(out_dir).resolve()
    if out.exists():
        raise CandidateError(f"the output directory exists: {out}")
    if not out.parent.is_dir():
        raise CandidateError(f"the parent of the output directory does not exist: {out.parent}")
    for forbidden in [Path(store_root)] + [Path(r) for r in roots.values()]:
        f = forbidden.resolve()
        if out == f or f in out.parents:
            raise CandidateError(f"the output directory must not be inside the registry or a source root: {f}")
    try:
        after = ledger.build_ledger(run, src_cat, ns_obj, amb_obj, mapping, roots)
        if after["problems"]:
            raise CandidateError("the import has problems:\n" + "\n".join(after["problems"]))
        if not after["complete"]:
            raise CandidateError("the ledger is not complete (a source is missing or unsupported); nothing is generated from a partial import")
        before = ledger.build_ledger(run, src_cat, ns_obj, amb_obj, {"schema": ledger.MAPPING_SCHEMA, "tokens": {}}, roots)
    except ledger.LedgerInputError as e:
        raise CandidateError(f"unusable inputs:\n{e}") from e
    f = check_mapping_diff(ledger.diff_ledgers(before, after), mapping, after["entries"])
    if f:
        raise CandidateError("the mapping does not account for the difference of the imports:\n" + "\n".join(x.line() for x in f))
    try:
        st = store.load(store_root)
    except store.StoreError as e:
        raise CandidateError(f"store: {e}") from e
    if blocking(st.findings):
        raise CandidateError("store has data errors:\n" + "\n".join(x.line() for x in st.findings))

    tokens = mapping["tokens"]
    unit_text = {}
    by_key = {}
    for e in after["entries"]:
        if e["class"] == "LABEL" and e["disposition"] == "MIGRATED_AS_ALIAS":
            by_key.setdefault(f"{e['namespace']}:{e['text']}", []).append(e)
    new_by_record, existing, declined = {}, [], []
    for key in sorted(tokens):
        d = tokens[key]
        if d["disposition"] != "MIGRATED_AS_ALIAS":
            declined.append(key)
            continue
        if d["record"] not in st.records:
            raise CandidateError(f"mapping {key}: the record {d['record']} is not in the store")
        occ = by_key[key]
        ns, value = key.split(":", 1)
        have = [a for a in st.records[d["record"]].obj.get("aliases", []) if isinstance(a, dict) and (a.get("namespace"), a.get("value")) == (ns, value)]
        if have:
            if have[0].get("status") != d["status"]:
                raise CandidateError(f"mapping {key}: {d['record']} already has this alias with the status {have[0].get('status')!r}, the mapping says {d['status']!r}")
            existing.append(key)
            continue
        first = next((o for o in occ if "line" in o), None)
        if first is None:
            raise CandidateError(f"mapping {key}: every occurrence is in a non-text (ODS) source; alias evidence is checked against UTF-8 text only, so no candidate is generated")
        ref = (first["source"], first["version"])
        if ref not in unit_text:
            v = sources.find_version(src_cat, *ref)
            data = sources.read_verified(src_cat, roots, *ref)
            unit_text[ref] = {u.id: u.text for u in units.read_units(units.suffix_of(v["location"]["path"]), data)}
        src = {"source": first["source"], "version": first["version"], "anchor": first["unit"], "quote": unit_text[ref][first["unit"]]}
        alias = {"namespace": ns, "value": value, "status": d["status"], "source": src,
                 "note": f"{len(occ)} occurrence(s) in the imported sources; this one is the first text occurrence (ledger entry #{first['n']})"}
        origins = {"namespace": ns, "value": value, "occurrences": [{k: o[k] for k in ("source", "version", "unit", "column", "text") if k in o} | ({"line": o["line"]} if "line" in o else {}) for o in occ]}
        new_by_record.setdefault(d["record"], []).append((alias, origins))

    synthetic = {r.id: copy.deepcopy(r.obj) for r in st.records.values()}
    for rid, items in new_by_record.items():
        synthetic[rid].setdefault("aliases", []).extend(a for a, _ in items)
    problems = [x for x in aliases.check_aliases(synthetic, ns_obj, src_cat, roots) if x.cls == "DATA_ERROR"]
    if problems:
        raise CandidateError("the candidate aliases fail the alias checks:\n" + "\n".join(x.line() for x in problems))

    out.mkdir()
    files = {}
    for rid in sorted(new_by_record):
        items = new_by_record[rid]
        obj = {"schema": CANDIDATE_SCHEMA, "record": rid, "aliases": [a for a, _ in items], "origins": [o for _, o in items]}
        rel = f"aliases/{rid}.json"
        (out / "aliases").mkdir(exist_ok=True)
        canon.write_record(out / rel, obj)
        files[rid] = (rel, obj)
    canon.write_record(out / "ledger-before.json", before)
    canon.write_record(out / "ledger-after.json", after)
    not_mapped = {}
    for e in after["entries"]:
        if e["disposition"] != "MIGRATED_AS_ALIAS":
            not_mapped[e["disposition"]] = not_mapped.get(e["disposition"], 0) + 1
    manifest = {"schema": MANIFEST_SCHEMA, "inputs": after["inputs"], "diff_check": "exact",
                "ledger_sha256": hashlib.sha256((out / "ledger-after.json").read_bytes()).hexdigest(),
                "ledger_before_sha256": hashlib.sha256((out / "ledger-before.json").read_bytes()).hexdigest(),
                "dispositions": after["summary"]["dispositions"], "classes": after["summary"]["classes"],
                "mapped": sorted(k for k in tokens if tokens[k]["disposition"] == "MIGRATED_AS_ALIAS"), "existing": sorted(existing), "declined": declined,
                "not_mapped": not_mapped,
                "records": [{"record": rid, "file": files[rid][0], "aliases": len(files[rid][1]["aliases"]),
                             "sha256": hashlib.sha256((out / files[rid][0]).read_bytes()).hexdigest()} for rid in sorted(files)]}
    canon.write_record(out / "MANIFEST.json", manifest)
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clxreg.candidates")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    for name in ("run", "catalog", "namespaces", "mapping", "store-root", "out"):
        g.add_argument(f"--{name}", required=True)
    g.add_argument("--ambiguity")
    g.add_argument("--root", action="append")
    a = ap.parse_args(argv)
    try:
        roots = sources.parse_roots(a.root)
        m = generate(ledger.load_input(a.run, "run"), ledger.load_input(a.catalog, "sources"), ledger.load_input(a.namespaces, "namespaces"),
                     ledger.load_input(a.ambiguity, "ambiguity") if a.ambiguity else None, ledger.load_input(a.mapping, "mapping"), roots, a.store_root, a.out)
    except (CandidateError, ledger.LedgerInputError, sources.SourceError, OSError) as e:
        print(f"candidates: {e}", file=sys.stderr)
        return 3
    print(f"output: {a.out}")
    print(f"candidate files: {len(m['records'])}, mapped: {len(m['mapped'])}, existing: {len(m['existing'])}, declined: {len(m['declined'])}")
    print(f"not mapped (counted, not dropped): {json.dumps(m['not_mapped'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
