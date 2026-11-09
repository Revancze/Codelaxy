"""IMP2-00 - guard of protected files: SHA-256 before/after every step, and nothing staged.

    python -m clxreg.protect check --manifest M [--repo R] [--root name=path ...]
    python -m clxreg.protect build --inventory I --map prefix=root ... --root name=path ... --out M

Reads only. `build` refuses to overwrite and refuses when a file on disk differs from the hash DOCUMENTED in the inventory
(the documented hash wins; a difference is a stop, never something to "repair").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from .findings import Finding, data_error

SCHEMA = 1


class BuildError(Exception):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_rel(rel: str) -> bool:
    p = Path(rel)
    return not p.is_absolute() and ".." not in p.parts and rel.strip() != ""


def check(manifest_path, root_overrides=None) -> list[Finding]:
    f: list[Finding] = []
    try:
        m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [data_error("PR-04", str(manifest_path), f"manifest unreadable: {e}")]
    if m.get("schema") != SCHEMA:
        return [data_error("PR-04", str(manifest_path), f"unsupported manifest schema {m.get('schema')!r}")]
    entries = m.get("entries") or []
    if not entries:
        return [data_error("PR-04", str(manifest_path), "manifest has no entries: the check would pass vacuously")]
    roots = dict(m.get("roots") or {})
    roots.update(root_overrides or {})
    for e in entries:
        name, rel, want = e.get("root"), e.get("path", ""), e.get("sha256", "")
        rec = f"{name}:{rel}"
        if name not in roots or not _safe_rel(rel) or not re.fullmatch(r"[0-9a-f]{64}", want or ""):
            f.append(data_error("PR-04", rec, "invalid manifest entry (unknown root, unsafe path or bad hash)"))
            continue
        p = Path(roots[name]).expanduser() / rel
        if not p.is_file():
            f.append(data_error("PR-01", rec, "protected file is missing"))
        elif sha256_file(p) != want:
            f.append(data_error("PR-02", rec, "protected file changed (SHA-256 differs from the manifest)"))
    return f


def check_staged(repo) -> list[Finding]:
    try:
        p = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"], capture_output=True, text=True, encoding="utf-8")
    except OSError as e:
        return [data_error("PR-04", str(repo), f"git not runnable: {e}")]
    if p.returncode != 0:
        return [data_error("PR-04", str(repo), "not a git repository or git failed")]
    staged = [x for x in p.stdout.splitlines() if x]
    if staged:
        return [data_error("PR-03", str(repo), "files are STAGED (no staging is allowed): " + ", ".join(staged[:5]))]
    return []


_LINE = re.compile(r"^([0-9a-f]{64})\s+(.+?)\s*$")


def build_from_inventory(inventory_path, prefix_map: dict, roots: dict, out_path) -> dict:
    out = Path(out_path)
    if out.exists():
        raise BuildError(f"refusing to overwrite {out}")
    documented: dict = {}
    for raw in Path(inventory_path).read_text(encoding="utf-8").splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        for part in m.group(2).split(";"):
            rel = re.split(r"\s{2,}", part.strip())[0].strip()
            if not rel:
                continue
            root = next((r for pre, r in prefix_map.items() if rel.startswith(pre)), None)
            if root is None:
                raise BuildError(f"no root mapped for documented path {rel!r}")
            key = (root, rel)
            if key in documented and documented[key] != m.group(1):
                raise BuildError(f"{rel}: documented with two different hashes")
            documented[key] = m.group(1)
    if not documented:
        raise BuildError("no documented hashes found in the inventory")
    problems = []
    for (root, rel), h in sorted(documented.items()):
        p = Path(roots[root]).expanduser() / rel
        if not p.is_file():
            problems.append(f"{rel}: missing on disk")
        elif sha256_file(p) != h:
            problems.append(f"{rel}: disk hash differs from the documented hash")
    if problems:
        raise BuildError("STOP, disk differs from the inventory:\n  " + "\n  ".join(problems))
    manifest = {"schema": SCHEMA, "machine_local": True, "roots": roots,
                "entries": [{"root": r, "path": p, "sha256": h, "source": "inventory"} for (r, p), h in sorted(documented.items())]}
    with open(out, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return manifest


def _kv(items):
    d = {}
    for it in items or []:
        k, _, v = it.partition("=")
        d[k] = v
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clxreg.protect")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--manifest", required=True)
    c.add_argument("--repo")
    c.add_argument("--root", action="append")
    b = sub.add_parser("build")
    b.add_argument("--inventory", required=True)
    b.add_argument("--map", action="append", required=True)
    b.add_argument("--root", action="append", required=True)
    b.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        f = check(a.manifest, _kv(a.root))
        if a.repo:
            f += check_staged(a.repo)
        for x in f:
            print(x.line())
        print("protect: %s (%d findings)" % ("FAIL" if f else "OK", len(f)))
        return 1 if f else 0
    try:
        m = build_from_inventory(a.inventory, _kv(a.map), _kv(a.root), a.out)
    except BuildError as e:
        print(e, file=sys.stderr)
        return 3
    print(f"manifest written: {a.out} ({len(m['entries'])} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
