"""IMP2-11 (a) - fingerprint of a DIRTY working tree.

`git_dirty_manifest(repo)`: HEAD plus (path, SHA-256 of the working-tree bytes) of every file git sees as different from HEAD, the paths git sees as deleted
and the untracked files that are not ignored. `tree_manifest(dir)`: (path, SHA-256) of every file of a directory that is not a git checkout (a copy
made for a test run), with the excluded build-output directory names recorded in the manifest. Neither contains times or the order of discovery; both
are canonical data and `digest()` is the fingerprint. Reading never changes or stages anything.
Known limit: the first one asks git what differs, so a change that git's own end-of-line normalisation hides (`* text=auto`) is not seen; `tree_manifest`
hashes raw bytes and does not have that limit.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import stat
from pathlib import Path

from . import canon

DEFAULT_EXCLUDES = ("bin", "obj")
_GIT = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false"]


class ManifestError(RuntimeError):
    pass


def _git(repo, *args) -> bytes:
    try:
        p = subprocess.run(_GIT + ["-C", str(repo), *args], capture_output=True)
    except OSError as e:
        raise ManifestError(f"cannot run git: {e}") from e
    if p.returncode != 0:
        raise ManifestError(f"git {' '.join(args[:2])} failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout


def _sha(path: Path) -> str:
    _reject_link(path)
    if not path.is_file():
        raise ManifestError(f"not a regular file: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _reject_link(path: Path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ManifestError(f"symbolic links and reparse points are not supported provenance inputs: {path}")


def _name(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ManifestError(f"a path is not valid UTF-8: {b!r}") from e


def git_dirty_manifest(repo) -> dict:
    repo = Path(repo)
    head = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    parts = [x for x in _git(repo, "diff", "--name-status", "--no-renames", "-z", "HEAD").split(b"\0") if x]
    if len(parts) % 2:
        raise ManifestError("unexpected output of git diff --name-status")
    changed, deleted = [], []
    for status, raw in zip(parts[0::2], parts[1::2]):
        rel = _name(raw)
        full = repo / rel
        if status[:1] == b"D" or not (full.exists() or full.is_symlink()):
            deleted.append(rel)
        else:
            changed.append({"path": rel, "sha256": _sha(full)})
    untracked = [{"path": _name(r), "sha256": _sha(repo / _name(r))} for r in _git(repo, "ls-files", "-z", "--others", "--exclude-standard").split(b"\0") if r]
    key = lambda e: e["path"]       # noqa: E731
    return {"kind": "git-dirty", "head": head, "changed": sorted(changed, key=key), "deleted": sorted(deleted), "untracked": sorted(untracked, key=key)}


def tree_manifest(root, excludes=DEFAULT_EXCLUDES) -> dict:
    root = Path(root)
    if not root.is_dir():
        raise ManifestError(f"not a directory: {root}")
    _reject_link(root)
    skip = set(excludes) | {".git"}
    files = []
    def unreadable(error):
        raise ManifestError(f"cannot enumerate provenance input: {error}") from error
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=unreadable):
        current = Path(dirpath)
        if current != root and (current / ".git").exists():
            raise ManifestError(f"nested repository is not a supported provenance input: {current}")
        for name in dirnames:
            if name not in skip:
                _reject_link(current / name)
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for f in filenames:
            if f == ".git":
                continue
            p = Path(dirpath) / f
            files.append({"path": p.relative_to(root).as_posix(), "sha256": _sha(p)})
    return {"kind": "tree", "excludes": sorted(set(excludes)), "files": sorted(files, key=lambda e: e["path"])}


def digest(manifest: dict) -> str:
    return canon.digest(manifest)
