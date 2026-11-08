"""IMP2-02 - record store: ID shape, one-file-per-record layout, next-id and the check against a base ref.

Layout: <root>/records/<TYPE>/<ID>.json with TYPE in REQ, SCN, EVD, MIL. Decisions (DEC) live in MADR files, not here.
Codes: DE-01 duplicate id, DE-02 malformed id / name / directory / form, DE-06 record deleted, renamed or re-identified against the base.
Everything here is read-only: nothing is created, changed or staged.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import canon
from .findings import blocking, data_error

STORED_TYPES = ("REQ", "SCN", "EVD", "MIL")
SCHEMA_VERSION = 1
_ID = re.compile(r"CLX-(REQ|SCN|EVD|DEC|MIL)-([0-9]{4,})")               # [0-9], not \d: no other Unicode digits
_LOOSE_NAME = re.compile(r"CLX-(REQ|SCN|EVD|DEC|MIL)-([0-9]+)\.json")      # also catches malformed names, so their number stays reserved
_RECORD_PATH = re.compile(r"records/(REQ|SCN|EVD|MIL)/[^/]+\.json")


class StoreError(RuntimeError):
    """The store cannot be examined at all (missing root, bad ref, no git). Never reported as a pass."""


@dataclass(frozen=True)
class Record:
    id: str
    type: str
    path: str
    obj: dict


@dataclass
class Store:
    records: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)


def parse_id(s):
    if not isinstance(s, str):
        return None
    m = _ID.fullmatch(s)
    return (m.group(1), int(m.group(2))) if m else None


def format_id(typ: str, n: int) -> str:
    if typ not in STORED_TYPES:
        raise StoreError(f"unknown record type {typ!r}; expected one of {', '.join(STORED_TYPES)}")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise StoreError("record numbers start at 1 (0000 is reserved for test vectors)")
    return f"CLX-{typ}-{n:04d}"


def _records_dir(root) -> Path:
    root = Path(root)
    if not root.is_dir():
        raise StoreError(f"registry root is not a directory: {root}")
    rd = root / "records"
    if not rd.is_dir():
        raise StoreError(f"no records/ directory under {root}")
    return rd


def _entries(path: Path):
    with os.scandir(path) as it:
        return sorted(it, key=lambda e: e.name)


def load(root) -> Store:
    rd = _records_dir(root)
    out = Store()
    groups: dict = {}                       # content id -> [paths]  (only readable files with a well-formed id)
    clean: dict = {}                        # path -> Record candidates that passed every identity check

    def err(code, path, msg):
        out.findings.append(data_error(code, path, msg))

    for top in _entries(rd):
        tpath = f"records/{top.name}"
        if top.is_symlink() or not top.is_dir() or top.name not in STORED_TYPES:
            err("DE-02", tpath, "unexpected entry in records/ (only the directories REQ, SCN, EVD, MIL are allowed)")
            continue
        typ = top.name
        for e in _entries(Path(top.path)):
            path = f"{tpath}/{e.name}"
            if e.is_symlink():
                err("DE-02", path, "symbolic links are not allowed in the store")
                continue
            if e.is_dir():
                err("DE-02", path, "subdirectories are not allowed in the store")
                continue
            if not e.name.endswith(".json"):
                err("DE-02", path, "not a record file (record files are named <ID>.json)")
                continue
            stem = e.name[:-len(".json")]
            problems = []
            sid = parse_id(stem)
            if sid is None:
                problems.append(f"file name {stem!r} is not a valid ID (CLX-<TYPE>-<4+ digits>)")
            elif sid[0] != typ:
                problems.append(f"the type in the file name ({sid[0]}) differs from its directory ({typ})")
            try:
                text = Path(e.path).read_bytes().decode("utf-8")
                obj = canon.loads(text)
            except (UnicodeDecodeError, canon.CanonError, OSError) as ex:
                err("DE-02", path, f"cannot read the record: {ex}")
                for p in problems:
                    err("DE-02", path, p)
                continue
            if not isinstance(obj, dict):
                err("DE-02", path, "a record must be a JSON object")
                continue
            if canon.dumps(obj) != text:
                problems.append("not in canonical form (UTF-8 without BOM, LF, 2 spaces, sorted keys, one trailing newline)")
            v = obj.get("schema_version")
            if type(v) is not int or v != SCHEMA_VERSION:
                problems.append(f"schema_version must be {SCHEMA_VERSION}, found {v!r}")
            rid = obj.get("id")
            parsed = parse_id(rid)
            if parsed is None:
                problems.append(f"id {rid!r} is not a valid ID")
            else:
                groups.setdefault(rid, []).append(path)
                if rid != stem:                                       # with the file-name check above this also pins the id's type to the directory
                    problems.append(f"id {rid!r} differs from the file name")
            if obj.get("type") != typ:
                problems.append(f"type field {obj.get('type')!r} differs from the directory ({typ})")
            for p in problems:
                err("DE-02", path, p)
            if not problems:
                clean[path] = Record(rid, typ, path, obj)

    dup = {p for paths in groups.values() if len(paths) > 1 for p in paths}
    for rid, paths in sorted(groups.items()):
        if len(paths) > 1:
            for p in paths:
                err("DE-01", p, f"id {rid} is used by {len(paths)} files: {', '.join(sorted(paths))}")
    for path, r in sorted(clean.items()):
        if path not in dup:                                   # a duplicated id has no winner: none of its files is loaded
            out.records[r.id] = r
    out.findings.sort(key=lambda f: (f.record, f.code, f.message))
    return out


# --- git -------------------------------------------------------------------------------------------------------------------------
def _git(root, *args) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, env=env)
    except OSError as e:
        raise StoreError(f"cannot run git: {e}") from e


def _resolve(root, ref) -> str:
    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\0" in ref:
        raise StoreError(f"invalid base ref {ref!r}")
    p = _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    sha = p.stdout.decode("utf-8", "replace").strip()
    if p.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise StoreError(f"base ref {ref!r} is not a commit of the repository containing {root}")
    return sha


def _nul_fields(raw: bytes):
    return [x.decode("utf-8", "surrogateescape") for x in raw.split(b"\0") if x != b""]


def _id_of(blob: bytes):
    try:
        o = canon.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, canon.CanonError):
        return None
    return o.get("id") if isinstance(o, dict) else None


def check_against_base(root, base) -> list:
    """DE-06: a record file of the base commit is missing or renamed in the working tree, or its id changed. New files are fine."""
    sha = _resolve(root, base)                                # the working tree may have lost records/ altogether: reported per file
    d = _git(root, "diff", "--name-status", "--no-renames", "--no-ext-diff", "--relative", "-z", sha, "--", "records")
    if d.returncode != 0:
        raise StoreError("git diff failed: " + d.stderr.decode("utf-8", "replace").strip())
    parts = _nul_fields(d.stdout)
    if len(parts) % 2:
        raise StoreError("unexpected output of git diff --name-status")
    out = []
    for status, path in zip(parts[0::2], parts[1::2]):
        if status[:1] == "D":
            out.append(data_error("DE-06", path, f"record file of the base commit {sha[:12]} is gone (deleted or renamed); records are never removed"))
        elif status[:1] == "M" and _RECORD_PATH.fullmatch(path):
            old = _git(root, "show", f"{sha}:./{path}")
            now = Path(root) / path
            if old.returncode != 0 or not now.is_file():
                continue
            before, after = _id_of(old.stdout), _id_of(now.read_bytes())
            if before is not None and after is not None and before != after:
                out.append(data_error("DE-06", path, f"id changed from {before} to {after}; an id is never changed"))
    out.sort(key=lambda f: (f.record, f.code, f.message))
    return out


def _base_numbers(root, typ, sha) -> list:
    p = _git(root, "ls-tree", "-r", "-z", "--name-only", sha, "--", "records")
    if p.returncode != 0:
        raise StoreError("git ls-tree failed: " + p.stderr.decode("utf-8", "replace").strip())
    nums = []
    for path in _nul_fields(p.stdout):
        m = _LOOSE_NAME.fullmatch(path.rsplit("/", 1)[-1])
        if m and m.group(1) == typ:
            nums.append(int(m.group(2)))
    return nums


def base_objects(root, base) -> dict:
    """{id: object} of the readable record files of the base commit (unreadable ones are skipped: the base is not ours to judge)."""
    sha = _resolve(root, base)
    p = _git(root, "ls-tree", "-r", "-z", "--name-only", sha, "--", "records")
    if p.returncode != 0:
        raise StoreError("git ls-tree failed: " + p.stderr.decode("utf-8", "replace").strip())
    out = {}
    for path in _nul_fields(p.stdout):
        if not _RECORD_PATH.fullmatch(path):
            continue
        blob = _git(root, "show", f"{sha}:./{path}")
        if blob.returncode != 0:
            continue
        try:
            obj = canon.loads(blob.stdout.decode("utf-8"))
        except (UnicodeDecodeError, canon.CanonError):
            continue
        if isinstance(obj, dict) and parse_id(obj.get("id")) is not None:
            out.setdefault(obj["id"], obj)
    return out


def next_id(root, typ: str, base=None) -> str:
    """max + 1 over every file (any content, any state) present now and, if given, in the base commit. Gaps are never filled."""
    if typ not in STORED_TYPES:
        raise StoreError(f"unknown record type {typ!r}; expected one of {', '.join(STORED_TYPES)}")
    rd = _records_dir(root)
    nums = [0]
    for top in _entries(rd):
        if top.is_dir() and not top.is_symlink() and top.name in STORED_TYPES:
            for e in _entries(Path(top.path)):
                m = _LOOSE_NAME.fullmatch(e.name)
                if m and m.group(1) == typ:
                    nums.append(int(m.group(2)))
    if base is not None:
        nums += _base_numbers(root, typ, _resolve(root, base))
    return format_id(typ, max(nums) + 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clxreg.store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--root", required=True)
    c.add_argument("--base")
    n = sub.add_parser("next-id")
    n.add_argument("type")
    n.add_argument("--root", required=True)
    n.add_argument("--base")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "next-id":
            print(next_id(a.root, a.type, a.base))
            return 0
        s = load(a.root)
        findings = list(s.findings)
        if a.base is not None:
            findings += check_against_base(a.root, a.base)
    except StoreError as e:
        print(f"store: {e}", file=sys.stderr)
        return 3
    for f in findings:
        print(f.line())
    print(f"store: {'FAIL' if blocking(findings) else 'OK'} (records: {len(s.records)}, findings: {len(findings)})")
    return 1 if blocking(findings) else 0


if __name__ == "__main__":
    sys.exit(main())
