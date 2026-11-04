"""Machine-local catalogs: a documented, reproducible way to build and check them, with no historical claim that is not backed by a literal basis.

`build-sources` turns a spec into `sources.json`. In the spec every version names its file, its full SHA-256 and, for BOTH the hash and the status, the
basis of the claim: a literal quote from another catalogued file that contains the hash / states the status, or (for the root record of a ratification)
the protected-files manifest, which holds the hash that was documented and verified against the disk. The builder reads every file, recomputes every
hash and checks every quote; one failure refuses the whole build. `check` rebuilds in memory and compares with the file on disk, then validates the
catalog, verifies the files, and checks that every namespace authority carries a quote that is literally in its pinned source.
Exit codes: 0 ok, 1 check found a difference or a data error, 3 refused or unusable input.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from . import canon, namespaces, sources
from .findings import blocking, data_error

SPEC_SCHEMA = "clx.catalog-spec/1"
_SOURCE_FIELDS = {"key", "title", "category", "versions"}
_SOURCE_OPTIONAL = {"subtype", "default_namespaces"}
_VERSION_FIELDS = {"id", "location", "sha256", "status", "basis"}
_VERSION_OPTIONAL = {"ratified_by"}


class SpecError(RuntimeError):
    pass


def _is_str(x):
    return isinstance(x, str) and x != ""


def _shape(spec):
    errs = []
    if not isinstance(spec, dict):
        raise SpecError("the spec must be a JSON object")
    for k in sorted(set(spec) - {"schema", "sources"}):
        errs.append(f"unknown field {k!r}")
    if spec.get("schema") != SPEC_SCHEMA:
        errs.append(f"schema must be {SPEC_SCHEMA!r}")
    if not isinstance(spec.get("sources"), list):
        errs.append("'sources' must be a list")
        raise SpecError("; ".join(errs))
    seen = set()
    for s in spec["sources"]:
        if not isinstance(s, dict) or not _SOURCE_FIELDS <= set(s) <= _SOURCE_FIELDS | _SOURCE_OPTIONAL or not isinstance(s.get("versions"), list):
            errs.append(f"a source needs exactly {sorted(_SOURCE_FIELDS)} (+ optional {sorted(_SOURCE_OPTIONAL)})")
            continue
        for v in s["versions"]:
            where = f"{s.get('key')}/{v.get('id') if isinstance(v, dict) else '?'}"
            if not isinstance(v, dict) or not _VERSION_FIELDS <= set(v) <= _VERSION_FIELDS | _VERSION_OPTIONAL:
                errs.append(f"{where}: a version needs exactly {sorted(_VERSION_FIELDS)} (+ optional ratified_by)")
                continue
            if (s["key"], v["id"]) in seen:
                errs.append(f"{where}: listed twice")
            seen.add((s["key"], v["id"]))
            b = v["basis"]
            if not isinstance(b, dict) or set(b) - {"sha256", "status"}:
                errs.append(f"{where}: basis must be {{sha256, status}}")
                continue
            for claim in ("sha256", "status"):
                c = b.get(claim)
                if c is None:
                    errs.append(f"{where}: basis.{claim} is missing: no claim without a basis")
                elif c == {"protected_manifest": True} and claim == "sha256":
                    continue
                elif not (isinstance(c, dict) and set(c) == {"quote_in", "quote"} and _is_str(c["quote"]) and isinstance(c["quote_in"], dict)
                          and set(c["quote_in"]) == {"source", "version"}):
                    errs.append(f"{where}: basis.{claim} must be {{quote_in: {{source, version}}, quote}}" + (" or {protected_manifest: true}" if claim == "sha256" else ""))
    if errs:
        raise SpecError("\n".join(errs))
    return seen


def build_sources(spec, roots, manifest=None) -> dict:
    index = _shape(spec)
    cache = {}
    versions = {}
    for s in spec["sources"]:
        for v in s["versions"]:
            versions[(s["key"], v["id"])] = v

    def read(ref):
        key = (ref[0], ref[1])
        if key not in cache:
            v = versions[key]
            loc = v["location"]
            if not (isinstance(loc, dict) and set(loc) == {"root", "path"} and loc["root"] in roots):
                raise SpecError(f"{key[0]}/{key[1]}: location root is not configured")
            base = Path(roots[loc["root"]]).resolve()
            p = (base / loc["path"]).resolve()
            try:
                p.relative_to(base)
            except ValueError:
                raise SpecError(f"{key[0]}/{key[1]}: the location leaves its root") from None
            if not p.is_file():
                raise SpecError(f"{key[0]}/{key[1]}: {loc['root']}:{loc['path']} does not exist")
            cache[key] = p.read_bytes()
        return cache[key]

    out_sources = []
    for s in spec["sources"]:
        out_versions = []
        for v in s["versions"]:
            where = f"{s['key']}/{v['id']}"
            data = read((s["key"], v["id"]))
            if hashlib.sha256(data).hexdigest() != v["sha256"]:
                raise SpecError(f"{where}: the file's SHA-256 differs from the declared one")
            notes = []
            b = v["basis"]
            if b["sha256"] == {"protected_manifest": True}:
                loc = v["location"]
                hit = [e for e in (manifest or {}).get("entries", []) if (e.get("root"), e.get("path")) == (loc["root"], loc["path"])]
                if not hit or hit[0].get("sha256") != v["sha256"]:
                    raise SpecError(f"{where}: no protected manifest entry with this path and hash")
                notes.append("sha256: protected manifest (hash documented and verified against the disk)")
            else:
                notes.append("sha256: " + _check_quote(b["sha256"], where, "sha256", versions, read, must_contain=v["sha256"], own=(s["key"], v["id"])))
            notes.append("status: " + _check_quote(b["status"], where, "status", versions, read))
            ov = {"id": v["id"], "sha256": v["sha256"], "bytes": len(data), "pinning": "sha256-only", "location": v["location"], "status": v["status"],
                  "note": "; ".join(notes)}
            if "ratified_by" in v:
                ov["ratified_by"] = v["ratified_by"]
            out_versions.append(ov)
        o = {k: s[k] for k in ("key", "title", "category") if k in s}
        o.update({k: s[k] for k in _SOURCE_OPTIONAL if k in s})
        o["versions"] = out_versions
        out_sources.append(o)
    cat = {"schema": sources.SCHEMA, "sources": out_sources}
    bad = sources.validate_catalog(cat)
    if blocking(bad):
        raise SpecError("the catalog built from the spec breaks the catalog rules:\n" + "\n".join(f.line() for f in bad if f.cls == "DATA_ERROR"))
    return cat


def _check_quote(c, where, claim, versions, read, must_contain=None, own=None):
    ref = (c["quote_in"]["source"], c["quote_in"]["version"])
    if ref not in versions:
        raise SpecError(f"{where}: basis.{claim} cites {ref[0]}/{ref[1]}, which is not in the spec")
    if claim == "sha256" and ref == own:
        raise SpecError(f"{where}: a version cannot document its own hash (basis.sha256 cites itself)")
    try:
        text = read(ref).decode("utf-8")
    except UnicodeDecodeError as e:
        raise SpecError(f"{where}: basis.{claim} cites {ref[0]}/{ref[1]}, which is not UTF-8 text ({e})") from e
    if c["quote"] not in text:
        raise SpecError(f"{where}: basis.{claim} quote is not a literal substring of {ref[0]}/{ref[1]}")
    if must_contain is not None and must_contain not in c["quote"]:
        raise SpecError(f"{where}: the basis quote does not contain the hash {must_contain[:12]}…")
    return f"{ref[0]}/{ref[1]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clxreg.localcat")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-sources")
    c = sub.add_parser("check")
    for p in (b, c):
        p.add_argument("--spec", required=True)
        p.add_argument("--manifest", required=True)
        p.add_argument("--root", action="append")
    b.add_argument("--out", required=True)
    c.add_argument("--catalog", required=True)
    c.add_argument("--namespaces", required=True)
    a = ap.parse_args(argv)
    try:
        roots = sources.parse_roots(a.root)
        spec, f1 = sources.load_canonical(a.spec, "spec")
        manifest = _load_json(a.manifest)
        if spec is None or f1:
            raise SpecError("; ".join(x.message for x in f1))
        built = build_sources(spec, roots, manifest)
        if a.cmd == "build-sources":
            canon.write_record(Path(a.out), built)
            print(f"written: {a.out} ({sum(len(s['versions']) for s in built['sources'])} versions, every claim with a verified basis)")
            return 0
        findings = []
        cat, f2 = sources.load_canonical(a.catalog, "sources")
        findings += f2
        if cat is not None:
            if canon.dumps(cat) != canon.dumps(built):
                findings.append(data_error("DE-13", "sources", "the catalog on disk differs from what the spec gives"))
            else:
                print("sources catalog reproduced from the spec")
            findings += sources.validate_catalog(cat)
            ns, f3 = sources.load_canonical(a.namespaces, "namespaces")
            findings += f3
            if ns is not None and not blocking(findings):          # a catalog equal to the build is valid and its files match: it was just built from them
                findings += namespaces.validate_namespaces(ns, cat)
                findings += namespaces.check_authorities(ns, cat, roots, require_quote=True)
        for f in findings:
            print(f.line())
        print(f"localcat check: {'FAIL' if blocking(findings) else 'OK'} ({len(findings)} findings)")
        return 1 if blocking(findings) else 0
    except (SpecError, sources.SourceError, OSError, ValueError) as e:
        print(f"localcat: {e}", file=sys.stderr)
        return 3


def _load_json(path):
    try:
        return canon.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, canon.CanonError) as e:
        raise SpecError(f"cannot read {path}: {e}") from e


if __name__ == "__main__":
    sys.exit(main())
