"""IMP2-03 - catalog of label namespaces: which label shapes exist, who is their authority, which ones merely share strings.

A namespace says: values of this shape (`label_pattern`, a full match) are labels of this kind, defined by `authority` (a pinned source version);
`distinct_from` lists namespaces that share strings but not meaning. Codes: DE-01 duplicate key, DE-02 malformed, DE-03 unknown reference,
DE-13 authority quote not in the pinned source, AD-04 source not available here.
"""
from __future__ import annotations

import re

from . import sources
from .findings import data_error

SCHEMA = "clx.namespaces/1"
STATUSES = ("LIVE", "FROZEN", "SUPERSEDED")
MAPS_TO = ("REQ", "SCN", "DEC", "MIL", "EXTERNAL")
_KEY = re.compile(r"[a-z0-9][a-z0-9.-]*")
_REQUIRED = {"key", "label_pattern", "meaning", "authority", "status", "maps_to", "distinct_from"}
_OPTIONAL = {"supersedes", "note"}
_REF_REQUIRED = {"source", "version"}
_REF_FIELDS = {"source", "version", "anchor", "fragment", "quote"}


def _s(x):
    return isinstance(x, str)


def validate_namespaces(obj, source_catalog=None) -> list:
    out = []

    def err(code, rec, msg):
        out.append(data_error(code, rec, msg))

    if not isinstance(obj, dict):
        return [data_error("DE-02", "namespaces", "the namespace catalog must be a JSON object")]
    for k in sorted(set(obj) - {"schema", "namespaces"}):
        err("DE-02", "namespaces", f"unknown top-level field {k!r}")
    if obj.get("schema") != SCHEMA:
        err("DE-02", "namespaces", f"schema must be {SCHEMA!r}, found {obj.get('schema')!r}")
    items = obj.get("namespaces")
    if not isinstance(items, list):
        err("DE-02", "namespaces", "'namespaces' must be a list")
        return _sorted(out)

    counts = {}
    for n in items:
        if isinstance(n, dict) and _s(n.get("key")) and _KEY.fullmatch(n["key"]):
            counts[n["key"]] = counts.get(n["key"], 0) + 1
    keys = set(counts)
    for i, n in enumerate(items):
        rec = f"namespaces[{i}]"
        if not isinstance(n, dict):
            err("DE-02", rec, "a namespace must be a JSON object")
            continue
        key = n.get("key")
        if _s(key) and _KEY.fullmatch(key):
            rec = f"namespaces:{key}"
            if counts[key] > 1:
                err("DE-01", rec, f"namespace key {key!r} is used {counts[key]} times")
        else:
            err("DE-02", rec, f"namespace key {key!r} must match [a-z0-9][a-z0-9.-]*")
        for f in sorted(_REQUIRED - set(n)):
            err("DE-02", rec, f"missing field {f!r}")
        for f in sorted(set(n) - _REQUIRED - _OPTIONAL):
            err("DE-02", rec, f"unknown field {f!r}")
        pat = n.get("label_pattern")
        if "label_pattern" in n:
            if not (_s(pat) and pat):
                err("DE-02", rec, "label_pattern must be a non-empty string")
            else:
                try:
                    if re.fullmatch(pat, "") is not None:
                        err("DE-02", rec, "label_pattern must not match the empty string")
                except re.error as e:
                    err("DE-02", rec, f"label_pattern is not a valid regular expression: {e}")
        if "meaning" in n and not (_s(n["meaning"]) and n["meaning"]):
            err("DE-02", rec, "meaning must be a non-empty string")
        if "status" in n and n["status"] not in STATUSES:
            err("DE-02", rec, f"status {n['status']!r} is not one of {', '.join(STATUSES)}")
        if "maps_to" in n and n["maps_to"] not in MAPS_TO:
            err("DE-02", rec, f"maps_to {n['maps_to']!r} is not one of {', '.join(MAPS_TO)}")
        if "note" in n and not _s(n["note"]):
            err("DE-02", rec, "note must be a string")
        _authority(n, rec, source_catalog, err)
        df = n.get("distinct_from")
        if "distinct_from" in n:
            if not (isinstance(df, list) and all(_s(x) for x in df)):
                err("DE-02", rec, "distinct_from must be a list of namespace keys")
            else:
                for x in df:
                    if x == key:
                        err("DE-02", rec, "a namespace cannot be distinct from itself")
                    elif x not in keys:
                        err("DE-03", rec, f"distinct_from names {x!r}, which is not a namespace of this catalog")
        if "supersedes" in n:
            sup = n["supersedes"]
            if not _s(sup):
                err("DE-02", rec, "supersedes must be a namespace key")
            elif sup == key:
                err("DE-02", rec, "a namespace cannot supersede itself")
            elif sup not in keys:
                err("DE-03", rec, f"supersedes names {sup!r}, which is not a namespace of this catalog")
    return _sorted(out)


def _authority(n, rec, source_catalog, err):
    a = n.get("authority")
    if "authority" not in n:
        return
    if not (isinstance(a, dict) and _REF_REQUIRED <= set(a) <= _REF_FIELDS and all(_s(a[k]) and a[k] for k in a)):
        err("DE-02", rec, "authority must be {\"source\": key, \"version\": id} with optional anchor, fragment and quote (non-empty strings)")
    elif source_catalog is not None:
        try:
            sources.find_version(source_catalog, a["source"], a["version"])
        except sources.SourceLookupError:
            err("DE-03", rec, f"authority {a['source']}/{a['version']} is not in the source catalog")


def check_authorities(obj, source_catalog, roots, require_quote=False) -> list:
    """Authority quotes against the verified bytes of the cited version (DE-13), skipped with AD-04 where the file is not here.
    With require_quote a namespace whose authority has no quote is an error: its meaning would rest on nothing checkable."""
    out = []
    for n in obj.get("namespaces", []) if isinstance(obj, dict) else []:
        a = n.get("authority") if isinstance(n, dict) else None
        if isinstance(a, dict) and "quote" in a and _s(a.get("source")) and _s(a.get("version")):
            out += sources.check_quote(source_catalog, roots, a)
        elif require_quote and isinstance(n, dict):
            out.append(data_error("DE-13", f"namespaces:{n.get('key')}", "the authority has no quote: the namespace rests on nothing checkable"))
    return _sorted(out)


def load_namespaces(path):
    return sources.load_canonical(path, "namespaces")


def _sorted(findings):
    return sorted(findings, key=lambda f: (f.record, f.code, f.message))
