"""Independent WORKTREE-GOLDEN-001 reference; no Codelaxy imports or output.

Frame each domain/field as uint32 big-endian UTF-8 byte length + bytes.
Git blob IDs hash b"blob <length>\\0" + raw content with SHA-1.
All files are regular, mode 100644; the baseline commit has an empty tree.
Run: python -B tests/golden_worktree_reference.py
"""

import hashlib
import struct
import subprocess


def fingerprint(domain, *parts):
    framed = bytearray()
    for part in (domain, *parts):
        encoded = part.encode("utf-8")
        framed.extend(struct.pack(">I", len(encoded)))
        framed.extend(encoded)
    return "sha256:" + hashlib.sha256(framed).hexdigest()


def blob(content):
    oid = hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()
    git_oid = subprocess.check_output(
        ["git", "hash-object", "--stdin", "--no-filters"], input=content
    ).decode("ascii").strip()
    assert oid == git_oid, (oid, git_oid)
    return oid


staged_oid = blob(b"staged\n")
loose_oid = blob(b"loose\n")
changed_oid = blob(b"changed\n")
commit = (
    b"tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\n"
    b"author Golden Tester <golden@example.invalid> 946684800 +0000\n"
    b"committer Golden Tester <golden@example.invalid> 946684800 +0000\n"
    b"\n"
    b"golden baseline\n"
)
commit_oid = hashlib.sha1(
    b"commit " + str(len(commit)).encode("ascii") + b"\0" + commit
).hexdigest()
h = fingerprint("codelaxy.snapshot.head.v1", commit_oid)
i = fingerprint("codelaxy.snapshot.index.v2", "100644", staged_oid, "0", "staged.txt")
s = fingerprint("codelaxy.snapshot.staged.v1", h, i)
untracked = fingerprint(
    "codelaxy.snapshot.untracked.v3",
    "path", "loose.txt", "kind", "regular", "mode", "100644", "oid", loose_oid,
)

for label, value in (("staged blob", staged_oid), ("loose blob", loose_oid),
                     ("changed blob", changed_oid), ("commit", commit_oid),
                     ("H", h), ("I", i), ("S", s), ("untracked", untracked)):
    print(f"{label}: {value}")

for label, oid in (("initial", staged_oid), ("changed", changed_oid)):
    tracked = fingerprint(
        "codelaxy.snapshot.tracked-worktree.v3",
        "path", "staged.txt", "state", "present", "kind", "regular",
        "mode", "100644", "oid", oid,
    )
    w = fingerprint("codelaxy.snapshot.worktree.v1", tracked, untracked)
    print(f"{label} tracked: {tracked}")
    print(f"{label} W: {w}")

print("PASS: all three blob OIDs match git hash-object --stdin --no-filters")
