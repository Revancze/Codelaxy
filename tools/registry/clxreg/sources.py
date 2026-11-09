"""IMP2-04 - catalog of source documents: pinned versions, verification against disk, literal quotes and status transitions.

A *source* has a category (RATIFIED, DRAFT, HISTORICAL, EXPERIMENTAL, EVIDENCE; vocabulary provisional until TD-8) and versions pinned by SHA-256.
Two byte-identities of "the same" document (ratified bytes, file marked afterwards) are two versions. A version never changes (DE-06).
Nothing is promoted automatically: a version is RATIFIED / RATIFIED-MARKED only with `ratified_by` pointing to a RATIFICATION-RECORD version
(the catalog records that a ratification was pinned; it cannot prove that it happened - that root of trust is a reviewed catalog change).
Codes: DE-01 duplicate key, DE-02 malformed, DE-03 unknown reference, DE-06 version removed or changed, DE-13 contradiction with the pinned/ratified
source, AD-04 weak pinning or source not available here (the check was skipped, not passed).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from . import canon, textsource
from .findings import advisory, blocking, data_error

SCHEMA = "clx.sources/1"
CATEGORIES = ("RATIFIED", "DRAFT", "HISTORICAL", "EXPERIMENTAL", "EVIDENCE")
SUBTYPES = ("RATIFICATION-RECORD", "PLANNING-VIEW", "GENERATED", "AUDIT-EVIDENCE")
STATUSES = ("RATIFIED", "RATIFIED-MARKED", "DRAFT", "HISTORICAL")
RATIFIED_STATUSES = ("RATIFIED", "RATIFIED-MARKED")
PINNINGS = ("git-blob", "sha256-only")
ALLOWED_STATUS_EDGES = {("DRAFT", "RATIFIED"), ("DRAFT", "HISTORICAL"), ("RATIFIED", "HISTORICAL"), ("RATIFIED-MARKED", "HISTORICAL")}

_KEY = re.compile(r"[a-z0-9][a-z0-9.-]*")
_ROOT = re.compile(r"[a-z0-9][a-z0-9-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GITID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SOURCE_FIELDS = {"key", "title", "category", "versions"}
_SOURCE_OPTIONAL = {"subtype", "default_namespaces"}
_VERSION_FIELDS = {"id", "sha256", "bytes", "pinning", "location", "status"}
_VERSION_OPTIONAL = {"ratified_by", "git_blob", "commit", "note"}


class SourceError(RuntimeError):
    """The environment, not the data, prevents a check (unreadable catalog file, bad arguments)."""


class SourceLookupError(SourceError):
    """Unknown source key or version id (DE-03)."""


class SourceUnavailable(SourceError):
    """The file is not available here (AD-04): nothing could be checked."""


class SourceMismatch(SourceError):
    """The bytes on disk differ from the pin (DE-13)."""


class SourceLocationError(SourceError):
    """The location leaves its root (DE-02)."""


def _s(x):
    return isinstance(x, str)


def _int(x):
    return type(x) is int


def _valid_path(p) -> bool:
    return (_s(p) and p != "" and "\\" not in p and ":" not in p and "\0" not in p
            and all(seg not in ("", ".", "..") for seg in p.split("/")))


# --- structure and consistency -------------------------------------------------------------------------------------------------
def validate_catalog(obj) -> list:
    out = []

    def err(code, rec, msg):
        out.append(data_error(code, rec, msg))

    if not isinstance(obj, dict):
        return [data_error("DE-02", "sources", "the catalog must be a JSON object")]
    for k in sorted(set(obj) - {"schema", "sources"}):
        err("DE-02", "sources", f"unknown top-level field {k!r}")
    if obj.get("schema") != SCHEMA:
        err("DE-02", "sources", f"schema must be {SCHEMA!r}, found {obj.get('schema')!r}")
    srcs = obj.get("sources")
    if not isinstance(srcs, list):
        err("DE-02", "sources", "'sources' must be a list")
        return _sorted(out)

    index = {}                                    # key -> source dict (first of its key)
    keyed = []                                    # (record name, source dict, {vid: version dict}) for sources that passed the structure checks
    counts = {}
    for i, s in enumerate(srcs):
        if isinstance(s, dict) and _s(s.get("key")) and _KEY.fullmatch(s["key"]):
            counts[s["key"]] = counts.get(s["key"], 0) + 1
    for i, s in enumerate(srcs):
        rec = f"sources[{i}]"
        if not isinstance(s, dict):
            err("DE-02", rec, "a source must be a JSON object")
            continue
        key = s.get("key")
        key_ok = _s(key) and bool(_KEY.fullmatch(key))
        if key_ok:
            rec = f"sources:{key}"
            index.setdefault(key, s)
            if counts[key] > 1:
                err("DE-01", rec, f"source key {key!r} is used {counts[key]} times")
        else:
            err("DE-02", rec, f"source key {key!r} must match [a-z0-9][a-z0-9.-]*")
        for f in sorted(_SOURCE_FIELDS - set(s)):
            err("DE-02", rec, f"missing field {f!r}")
        for f in sorted(set(s) - _SOURCE_FIELDS - _SOURCE_OPTIONAL):
            err("DE-02", rec, f"unknown field {f!r}")
        if "title" in s and (not _s(s["title"]) or not s["title"]):
            err("DE-02", rec, "title must be a non-empty string")
        cat_ok = s.get("category") in CATEGORIES
        if "category" in s and not cat_ok:
            err("DE-02", rec, f"category {s['category']!r} is not one of {', '.join(CATEGORIES)}")
        if "subtype" in s and s["subtype"] not in SUBTYPES:
            err("DE-02", rec, f"subtype {s['subtype']!r} is not one of {', '.join(SUBTYPES)}")
        dn = s.get("default_namespaces")
        if "default_namespaces" in s and not (isinstance(dn, list) and all(_s(x) and x for x in dn)):
            err("DE-02", rec, "default_namespaces must be a list of non-empty strings")
        vs = s.get("versions")
        if not isinstance(vs, list) or not vs:
            if "versions" in s:
                err("DE-02", rec, "versions must be a non-empty list")
            continue
        vcounts = {}
        for v in vs:
            if isinstance(v, dict) and _s(v.get("id")) and _KEY.fullmatch(v["id"]):
                vcounts[v["id"]] = vcounts.get(v["id"], 0) + 1
        versions = {}
        for j, v in enumerate(vs):
            vrec = f"{rec}/#{j}"
            if not isinstance(v, dict):
                err("DE-02", vrec, "a version must be a JSON object")
                continue
            vid = v.get("id")
            if _s(vid) and _KEY.fullmatch(vid):
                vrec = f"{rec}/{vid}"
                versions.setdefault(vid, v)
                if vcounts[vid] > 1:
                    err("DE-01", vrec, f"version id {vid!r} is used {vcounts[vid]} times in this source")
            else:
                err("DE-02", vrec, f"version id {vid!r} must match [a-z0-9][a-z0-9.-]*")
            _check_version(v, vrec, err)
        keyed.append((rec, s, versions))

    for rec, s, versions in keyed:
        subtype = s.get("subtype")
        statuses = [v.get("status") for v in versions.values()]
        has_ratified = any(st in RATIFIED_STATUSES for st in statuses)
        if s.get("category") == "RATIFIED" and not has_ratified:
            err("DE-13", rec, "category RATIFIED, but no version has the status RATIFIED or RATIFIED-MARKED (no automatic promotion)")
        if s.get("category") in CATEGORIES and s.get("category") != "RATIFIED" and has_ratified:
            err("DE-13", rec, f"category {s['category']} contains a RATIFIED version; ratified statuses exist only in a RATIFIED source")
        for vid, v in versions.items():
            vrec = f"{rec}/{vid}"
            st = v.get("status")
            rb = v.get("ratified_by")
            if st in RATIFIED_STATUSES:
                if subtype == "RATIFICATION-RECORD":
                    if "ratified_by" in v:
                        err("DE-13", vrec, "a ratification record is the root of the chain and has no ratified_by")
                    continue
                if "ratified_by" not in v:
                    err("DE-13", vrec, f"status {st} needs ratified_by (a pinned RATIFICATION-RECORD version): ratification is never assumed")
                    continue
            elif "ratified_by" in v:
                err("DE-13", vrec, f"ratified_by is allowed only on RATIFIED / RATIFIED-MARKED versions, not on {st!r}")
                continue
            if "ratified_by" not in v:
                continue
            if not (isinstance(rb, dict) and set(rb) == {"source", "version"} and _s(rb["source"]) and _s(rb["version"])):
                err("DE-02", vrec, "ratified_by must be {\"source\": key, \"version\": id}")
                continue
            target = index.get(rb["source"])
            tver = next((x for x in target.get("versions", []) if isinstance(x, dict) and x.get("id") == rb["version"]), None) \
                if target and isinstance(target.get("versions"), list) else None
            if target is None or tver is None:
                err("DE-03", vrec, f"ratified_by points to {rb['source']}/{rb['version']}, which is not in the catalog")
            elif target.get("subtype") != "RATIFICATION-RECORD":
                err("DE-13", vrec, f"ratified_by must point to a RATIFICATION-RECORD source; {rb['source']} is not one")
            elif tver.get("status") != "RATIFIED":
                err("DE-13", vrec, f"ratified_by points to {rb['source']}/{rb['version']}, whose status is {tver.get('status')!r}, not RATIFIED")
    return _sorted(out)


def _check_version(v, rec, err):
    for f in sorted(_VERSION_FIELDS - set(v)):
        err("DE-02", rec, f"missing field {f!r}")
    for f in sorted(set(v) - _VERSION_FIELDS - _VERSION_OPTIONAL):
        err("DE-02", rec, f"unknown field {f!r}")
    if "sha256" in v and not (_s(v["sha256"]) and _SHA256.fullmatch(v["sha256"])):
        err("DE-02", rec, "sha256 must be 64 lowercase hex characters")
    if "bytes" in v and not (_int(v["bytes"]) and v["bytes"] >= 0):
        err("DE-02", rec, "bytes must be a non-negative integer")
    if "status" in v and v["status"] not in STATUSES:
        err("DE-02", rec, f"status {v['status']!r} is not one of {', '.join(STATUSES)}")
    if "note" in v and not _s(v["note"]):
        err("DE-02", rec, "note must be a string")
    loc = v.get("location")
    if "location" in v:
        if not (isinstance(loc, dict) and set(loc) == {"root", "path"}):
            err("DE-02", rec, "location must be {\"root\": key, \"path\": relative path}")
        else:
            if not (_s(loc["root"]) and _ROOT.fullmatch(loc["root"])):
                err("DE-02", rec, "location.root must match [a-z0-9][a-z0-9-]*")
            if not _valid_path(loc["path"]):
                err("DE-02", rec, "location.path must be a relative POSIX path without '..', '.', empty segments, ':' or backslashes")
    p = v.get("pinning")
    if "pinning" in v and p not in PINNINGS:
        err("DE-02", rec, f"pinning {p!r} is not one of {', '.join(PINNINGS)}")
    if p == "git-blob":
        for f in ("git_blob", "commit"):
            if not (_s(v.get(f)) and _GITID.fullmatch(v[f])):
                err("DE-02", rec, f"git-blob pinning needs {f} (40 or 64 lowercase hex characters)")
    elif p == "sha256-only":
        for f in ("git_blob", "commit"):
            if f in v:
                err("DE-02", rec, f"{f} is meaningless with sha256-only pinning")


def _sorted(findings):
    return sorted(findings, key=lambda f: (f.record, f.code, f.message))


def load_catalog(path):
    """(object or None, findings): the form only (UTF-8, canonical JSON); the rules are validate_catalog's."""
    return load_canonical(path, "sources")


def load_canonical(path, record):
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise SourceError(f"cannot read {path}: {e}") from e
    try:
        text = data.decode("utf-8")
        obj = canon.loads(text)
    except (UnicodeDecodeError, canon.CanonError) as e:
        return None, [data_error("DE-02", record, f"cannot read the catalog: {e}")]
    if canon.dumps(obj) != text:
        return obj, [data_error("DE-02", record, "the catalog is not in canonical form")]
    return obj, []


# --- bytes on disk ----------------------------------------------------------------------------------------------------------------
def find_version(obj, key, vid):
    for s in obj.get("sources", []) if isinstance(obj, dict) else []:
        if isinstance(s, dict) and s.get("key") == key:
            for v in s.get("versions", []):
                if isinstance(v, dict) and v.get("id") == vid:
                    return v
    raise SourceLookupError(f"{key}/{vid} is not in the catalog")


def read_verified(obj, roots, key, vid) -> bytes:
    v = find_version(obj, key, vid)
    root, rel = v["location"]["root"], v["location"]["path"]
    if root not in roots:
        raise SourceUnavailable(f"root {root!r} is not configured")
    base = Path(roots[root]).resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise SourceLocationError(f"{rel!r} resolves outside the root {root!r}") from None
    if not target.exists():
        raise SourceUnavailable(f"{root}:{rel} does not exist")
    if not target.is_file():
        raise SourceMismatch(f"{root}:{rel} is not a regular file")
    data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != v["sha256"] or len(data) != v["bytes"]:
        raise SourceMismatch(f"{root}:{rel} differs from the pinned version "
                             f"(pinned sha256 {v['sha256'][:12]}…, {v['bytes']} bytes; found sha256 {hashlib.sha256(data).hexdigest()[:12]}…, {len(data)} bytes)")
    return data


def verified_text(obj, roots, key, vid) -> str:
    """Text of a version, only if its bytes match the pin."""
    return textsource.decode(read_verified(obj, roots, key, vid))


def find_label_in(obj, roots, key, vid, label) -> list:
    return textsource.find_label(verified_text(obj, roots, key, vid), label)


def _iter_versions(obj):
    for s in obj.get("sources", []):
        for v in s.get("versions", []):
            yield s["key"], v


def verify_files(obj, roots) -> list:
    out = []
    for key, v in _iter_versions(obj):
        rec = f"sources:{key}/{v['id']}"
        if v["pinning"] == "sha256-only":
            out.append(advisory("AD-04", rec, "pinning is sha256-only (outside git): the version is identified by its hash alone"))
        try:
            read_verified(obj, roots, key, v["id"])
        except SourceUnavailable as e:
            out.append(advisory("AD-04", rec, f"source file not available in this environment ({e}); hash and quote checks skipped"))
        except SourceMismatch as e:
            out.append(data_error("DE-13", rec, str(e)))
        except SourceLocationError as e:
            out.append(data_error("DE-02", rec, str(e)))
    return _sorted(out)


def check_quote(obj, roots, ref) -> list:
    """DE-13 unless `ref['quote']` is a literal substring of the *verified* bytes of the cited version."""
    if not (isinstance(ref, dict) and _s(ref.get("source")) and _s(ref.get("version")) and _s(ref.get("quote")) and ref["quote"]):
        return [data_error("DE-02", "sources", "a source reference needs string fields source, version and a non-empty quote")]
    key, vid = ref["source"], ref["version"]
    rec = f"sources:{key}/{vid}"
    try:
        text = verified_text(obj, roots, key, vid)
    except SourceLookupError as e:
        return [data_error("DE-03", rec, str(e))]
    except SourceUnavailable as e:
        return [advisory("AD-04", rec, f"source file not available in this environment ({e}); quote check skipped")]
    except SourceMismatch as e:
        return [data_error("DE-13", rec, f"the quote cannot be checked: {e}")]
    except SourceLocationError as e:
        return [data_error("DE-02", rec, str(e))]
    except textsource.SourceTextError as e:
        return [data_error("DE-13", rec, f"the pinned bytes are not UTF-8 text; the quote cannot be checked ({e})")]
    if not textsource.contains_quote(text, ref["quote"]):
        return [data_error("DE-13", rec, "the quote is not a literal substring of the pinned version")]
    return []


# --- changes between two catalogs -------------------------------------------------------------------------------------------------
def _index(obj) -> dict:
    out = {}
    for s in obj.get("sources", []) if isinstance(obj, dict) and isinstance(obj.get("sources"), list) else []:
        if isinstance(s, dict) and _s(s.get("key")) and isinstance(s.get("versions"), list):
            out.setdefault(s["key"], {v["id"]: v for v in s["versions"] if isinstance(v, dict) and _s(v.get("id"))})
    return out


def check_transition(old, new) -> list:
    """Rules for a catalog that already existed: nothing is removed, bytes never change, statuses move only along allowed edges."""
    out = []
    o, n = _index(old), _index(new)
    for key, versions in o.items():
        if key not in n:
            out.append(data_error("DE-06", f"sources:{key}", "source removed; sources are never removed"))
            continue
        for vid, ov in versions.items():
            rec = f"sources:{key}/{vid}"
            nv = n[key].get(vid)
            if nv is None:
                out.append(data_error("DE-06", rec, "version removed; versions are never removed"))
                continue
            for f in ("sha256", "bytes"):
                if ov.get(f) != nv.get(f):
                    out.append(data_error("DE-06", rec, f"{f} of an existing version changed; a changed document is a new version"))
            if "ratified_by" in ov and ov["ratified_by"] != nv.get("ratified_by"):
                out.append(data_error("DE-06", rec, "ratified_by of an existing version changed"))
            a, b = ov.get("status"), nv.get("status")
            if a == b:
                continue
            if (a, b) not in ALLOWED_STATUS_EDGES:
                out.append(data_error("DE-13", rec, f"status {a} -> {b} is not an allowed transition"))
            elif b == "RATIFIED" and "ratified_by" not in nv:
                out.append(data_error("DE-13", rec, "promotion to RATIFIED needs ratified_by: statuses are never promoted without a source"))
    return _sorted(out)


# --- command line -----------------------------------------------------------------------------------------------------------------
def parse_roots(items):
    roots = {}
    for it in items or []:
        k, eq, v = it.partition("=")
        if not eq or not k or not v:
            raise SourceError(f"--root expects key=directory, got {it!r}")
        roots[k] = v
    return roots


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clxreg.sources")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--catalog", required=True)
    c.add_argument("--root", action="append")
    c.add_argument("--old-catalog")
    a = ap.parse_args(argv)
    try:
        roots = parse_roots(a.root)
        obj, findings = load_catalog(a.catalog)
        old = None
        if a.old_catalog:
            old, of = load_catalog(a.old_catalog)
            findings += of
        if obj is not None:
            findings += validate_catalog(obj)
            if not blocking(findings):
                findings += verify_files(obj, roots)
                if old is not None:
                    findings += check_transition(old, obj)
            elif old is not None:
                findings += check_transition(old, obj)
    except SourceError as e:
        print(f"sources: {e}", file=sys.stderr)
        return 3
    for f in findings:
        print(f.line())
    n_src = len(obj["sources"]) if isinstance(obj, dict) and isinstance(obj.get("sources"), list) else 0
    n_ver = sum(len(s.get("versions", [])) for s in obj["sources"] if isinstance(s, dict) and isinstance(s.get("versions"), list)) if n_src else 0
    adv = sum(1 for f in findings if f.cls == "ADVISORY")
    print(f"sources: {'FAIL' if blocking(findings) else 'OK'} (sources: {n_src}, versions: {n_ver}, advisories: {adv})")
    return 1 if blocking(findings) else 0


if __name__ == "__main__":
    sys.exit(main())
