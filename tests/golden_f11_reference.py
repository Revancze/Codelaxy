"""F11 independent Git snapshot fingerprint reference (Python stdlib only).

Compute Git object IDs and Codelaxy fingerprint frames using hashlib, not the
C# implementation. Git is used only as a second, independent fixture check.
Fail closed if named F11 literals in the C# tests drift from Python's computed
results. Real-Git symlink checks require Unix (or --require-real-symlink).

Run: python -B tests/golden_f11_reference.py
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


COMMIT_BYTES = (
    b"tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\n"
    b"author Golden Tester <golden@example.invalid> 946684800 +0000\n"
    b"committer Golden Tester <golden@example.invalid> 946684800 +0000\n"
    b"\n"
    b"golden baseline\n"
)
CONTENT = {"a.txt": b"alpha\n", "b.txt": b"charlie\n", "c.txt": b"bravo\n"}
EXPECTED = {
    "tracked_I": "sha256:0938a02f94788084ce6957893b5c485178d86bb7725eb6cf2b69a3c4d18d7973",
    "tracked_S": "sha256:2a5539e74818aca17f6c381c990bde98171c35cb0cc8cf0b82127f6d2027f06a",
    "tracked_W": "sha256:23fd050198a17b12206d7ab1bb9c39ab17a8df2106b61f37d82cbaeeb7977897",
    "untracked_W": "sha256:c08c07398df974ee8a5973e392a96df2512553bb211609f79b342b7ca531afc5",
    "missing_W": "sha256:7746826a6606ab10bbbd6c47d4d34d69862c02836e41ee6f210321e22d659f4b",
    "directory_W": "sha256:91227ae363aa7ae7bb48791bbcd665bd3b2bc43e75ca98ec563674ce3afcb289",
    "link_a_W": "sha256:753ced1332e5fbe22d4ba06fb67b68eeb2280b6935898621e833baf642579f4d",
    "link_c_W": "sha256:379d4d0fcf213bc3675488a157fb70717e140f4f5adbdcd5fde9bfdee6989643",
}


def git_object_oid(kind: str, payload: bytes) -> str:
    header = kind.encode("ascii") + b" " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


def fingerprint(domain: str, *fields: str) -> str:
    digest = hashlib.sha256()
    for field in (domain, *fields):
        value = field.encode("utf-8", errors="strict")
        digest.update(struct.pack(">I", len(value)))
        digest.update(value)
    return "sha256:" + digest.hexdigest()


def index_fingerprint(index: dict[str, tuple[str, bytes]]) -> str:
    fields = []
    for path in sorted(index):
        mode, data = index[path]
        fields.extend((mode, git_object_oid("blob", data), "0", path))
    return fingerprint("codelaxy.snapshot.index.v2", *fields)


def tracked_fingerprint(
    index: dict[str, tuple[str, bytes]],
    worktree: dict[str, tuple[str, str, str | None, bytes | None]],
    *,
    object_ids: dict[str, str] | None = None,
) -> str:
    """Tuple: state, kind, mode, content; missing skips kind/mode/OID.

    A directory type conflict emits kind=directory but no mode or OID.
    For present symlinks, content is the raw link-target text.
    """
    fields = []
    for path in sorted(index):
        state, kind, mode, data = worktree[path]
        fields.extend(("path", path, "state", state))
        if state in ("missing", "unmaterialized"):
            continue
        fields.extend(("kind", kind))
        if state == "type-conflict":
            if kind != "directory":
                raise ValueError("type-conflict must be a directory")
            continue
        if state != "present" or mode is None or data is None:
            raise ValueError(f"invalid present entry: {path}")
        oid = git_object_oid("blob", data) if object_ids is None else object_ids[path]
        fields.extend(("mode", mode, "oid", oid))
    return fingerprint("codelaxy.snapshot.tracked-worktree.v3", *fields)


def untracked_fingerprint(
    untracked: dict[str, tuple[str, str, bytes]],
    *,
    object_ids: dict[str, str] | None = None,
) -> str:
    fields = []
    for path in sorted(untracked):
        kind, mode, data = untracked[path]
        oid = git_object_oid("blob", data) if object_ids is None else object_ids[path]
        fields.extend(("path", path, "kind", kind, "mode", mode, "oid", oid))
    return fingerprint("codelaxy.snapshot.untracked.v3", *fields)


def snapshot(
    index: dict[str, tuple[str, bytes]],
    tracked: dict[str, tuple[str, str, str | None, bytes | None]],
    untracked: dict[str, tuple[str, str, bytes]],
    *,
    tracked_oids: dict[str, str] | None = None,
    untracked_oids: dict[str, str] | None = None,
) -> dict[str, str]:
    head = fingerprint("codelaxy.snapshot.head.v1", git_object_oid("commit", COMMIT_BYTES))
    i = index_fingerprint(index)
    return {
        "H": head,
        "I": i,
        "S": fingerprint("codelaxy.snapshot.staged.v1", head, i),
        "W": fingerprint(
            "codelaxy.snapshot.worktree.v1",
            tracked_fingerprint(index, tracked, object_ids=tracked_oids),
            untracked_fingerprint(untracked, object_ids=untracked_oids),
        ),
    }


def present(data: bytes) -> tuple[str, str, str, bytes]:
    return ("present", "regular", "100644", data)


def assert_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def check_reference() -> dict[str, dict[str, str]]:
    index = {path: ("100644", data) for path, data in CONTENT.items()}
    full = {path: present(data) for path, data in CONTENT.items()}
    tracked_a = snapshot(index, full, {})
    untracked_a = snapshot(
        {}, {}, {path: ("regular", "100644", data) for path, data in CONTENT.items()}
    )

    for name, actual in (
        ("tracked_I", tracked_a["I"]),
        ("tracked_S", tracked_a["S"]),
        ("tracked_W", tracked_a["W"]),
        ("untracked_W", untracked_a["W"]),
    ):
        assert_equal(name, actual, EXPECTED[name])

    # F11-B: b.txt still exists in index, but is missing or is a directory.
    missing = dict(full)
    missing["b.txt"] = ("missing", "", None, None)
    directory = dict(full)
    directory["b.txt"] = ("type-conflict", "directory", None, None)
    tracked_missing = snapshot(index, missing, {})
    tracked_directory = snapshot(index, directory, {})
    for label, candidate in (("missing", tracked_missing), ("directory", tracked_directory)):
        for stable in ("H", "I", "S"):
            assert_equal(f"F11-B {label} {stable}", candidate[stable], tracked_a[stable])
        if candidate["W"] == tracked_a["W"]:
            raise AssertionError(f"F11-B {label} failed to change W")
    if tracked_missing["W"] == tracked_directory["W"]:
        raise AssertionError("F11-B missing and type-conflict were conflated")
    assert_equal("F11-B missing W", tracked_missing["W"], EXPECTED["missing_W"])
    assert_equal("F11-B directory W", tracked_directory["W"], EXPECTED["directory_W"])

    # F11-C must match C#: only a.txt, c.txt, b.link (NO b.txt).
    regular = {path: ("regular", "100644", CONTENT[path]) for path in ("a.txt", "c.txt")}
    link_a = dict(regular)
    link_a["b.link"] = ("symlink", "120000", b"a.txt")
    link_c = dict(regular)
    link_c["b.link"] = ("symlink", "120000", b"c.txt")
    untracked_link_a = snapshot({}, {}, link_a)
    untracked_link_c = snapshot({}, {}, link_c)
    for stable in ("H", "I", "S"):
        assert_equal(f"F11-C {stable}", untracked_link_a[stable], untracked_link_c[stable])
    if untracked_link_a["W"] == untracked_link_c["W"]:
        raise AssertionError("F11-C missed symlink retarget")
    assert_equal("F11-C a.txt link W", untracked_link_a["W"], EXPECTED["link_a_W"])
    assert_equal("F11-C c.txt link W", untracked_link_c["W"], EXPECTED["link_c_W"])

    # F11-D / M6-M7: sort OIDs separately from paths and try to pair them.
    actual_oids = [git_object_oid("blob", CONTENT[path]) for path in sorted(CONTENT)]
    independently_sorted = sorted(actual_oids)
    if actual_oids == independently_sorted:
        raise AssertionError("F11-D fixture does not distinguish path order from OID order")
    mutant_fields = []
    for path, oid in zip(sorted(CONTENT), independently_sorted):
        mutant_fields.extend(
            ("path", path, "state", "present", "kind", "regular", "mode", "100644", "oid", oid)
        )
    bad_tracked = fingerprint("codelaxy.snapshot.tracked-worktree.v3", *mutant_fields)
    bad_w = fingerprint("codelaxy.snapshot.worktree.v1", bad_tracked, untracked_fingerprint({}))
    if bad_w == tracked_a["W"]:
        raise AssertionError("F11-D tracked sorted-OID mutant survived")

    mutant_untracked_fields = []
    for path, oid in zip(sorted(CONTENT), independently_sorted):
        mutant_untracked_fields.extend(
            ("path", path, "kind", "regular", "mode", "100644", "oid", oid)
        )
    bad_untracked = fingerprint("codelaxy.snapshot.untracked.v3", *mutant_untracked_fields)
    bad_untracked_w = fingerprint(
        "codelaxy.snapshot.worktree.v1",
        tracked_fingerprint({}, {}),
        bad_untracked,
    )
    if bad_untracked_w == untracked_a["W"]:
        raise AssertionError("F11-D untracked sorted-OID mutant survived")

    # F11-D / M9: exact incorrect indexed association loses c.txt.
    # The production mutant returns Failure rather than a valid W; assert that
    # failure, AND separately calculate a full but incorrectly paired W.
    filtered_tracked = ["a.txt", "c.txt"]
    bad_tracked_oids = dict(zip(
        sorted(index), (git_object_oid("blob", CONTENT[p]) for p in filtered_tracked)
    ))
    assert_equal("M9 shifted b.txt OID", bad_tracked_oids["b.txt"],
                 git_object_oid("blob", CONTENT["c.txt"]))
    try:
        snapshot(index, missing, {}, tracked_oids=bad_tracked_oids)
    except KeyError as error:
        assert_equal("M9 lost hash path", error.args[0], "c.txt")
    else:
        raise AssertionError("M9 incomplete tracked OID mapping incorrectly produced W")
    swapped_tracked_oids = {
        "a.txt": git_object_oid("blob", CONTENT["c.txt"]),
        "c.txt": git_object_oid("blob", CONTENT["a.txt"]),
    }
    if snapshot(index, missing, {}, tracked_oids=swapped_tracked_oids)["W"] == tracked_missing["W"]:
        raise AssertionError("M9 valid but misattributed tracked OIDs produced golden W")

    # F11-D / M8: unfiltered path list contains b.link; filtered regular
    # hashes are for a.txt/c.txt. The faulty zip overwrites the symlink OID
    # and loses c.txt, which MUST prevent snapshot construction.
    filtered_untracked = ["a.txt", "c.txt"]
    bad_untracked_oids = {"b.link": git_object_oid("blob", b"a.txt")}
    bad_untracked_oids.update(zip(
        sorted(link_a), (git_object_oid("blob", CONTENT[p]) for p in filtered_untracked)
    ))
    assert_equal("M8 overwrote link OID", bad_untracked_oids["b.link"],
                 git_object_oid("blob", CONTENT["c.txt"]))
    try:
        snapshot({}, {}, link_a, untracked_oids=bad_untracked_oids)
    except KeyError as error:
        assert_equal("M8 lost hash path", error.args[0], "c.txt")
    else:
        raise AssertionError("M8 incomplete untracked OID mapping incorrectly produced W")
    swapped_untracked_oids = {
        "a.txt": git_object_oid("blob", CONTENT["c.txt"]),
        "b.link": git_object_oid("blob", b"a.txt"),
        "c.txt": git_object_oid("blob", CONTENT["a.txt"]),
    }
    if snapshot({}, {}, link_a, untracked_oids=swapped_untracked_oids)["W"] == untracked_link_a["W"]:
        raise AssertionError("M8 valid but misattributed untracked OIDs produced golden W")

    print("F11-A: tracked I/S/W and untracked W match four fixed Golden values")
    print("F11-B: missing/directory match two fixed W values; H/I/S invariant")
    print("F11-C: symlink retarget matches two fixed W values; H/I/S invariant")
    print("F11-D: sorted-OID W changes; M8/M9 incomplete mappings rejected and shifted W changes")
    print("F11-B missing W:", tracked_missing["W"])
    print("F11-B directory W:", tracked_directory["W"])
    print("F11-C link to a.txt W:", untracked_link_a["W"])
    print("F11-C link to c.txt W:", untracked_link_c["W"])
    return {"tracked": tracked_a, "untracked": untracked_a,
            "missing": tracked_missing, "directory": tracked_directory,
            "link_a": untracked_link_a, "link_c": untracked_link_c}



def _csharp_constant(section: str, name: str) -> str:
    """Extract exactly one specifically named SHA-256 constant, never a loose hash."""
    pattern = rf"\bconst\s+string\s+{re.escape(name)}\s*=\s*\"(sha256:[0-9a-f]{{64}})\"\s*;"
    values = re.findall(pattern, section)
    if len(values) != 1:
        raise AssertionError(f"C# Golden constant {name}: expected exactly one, got {len(values)}")
    return values[0]


def check_csharp_contract(csharp_file: Path, results: dict[str, dict[str, str]]) -> None:
    """Independently computed Python values must equal the named C# test pins."""
    source = csharp_file.read_text(encoding="utf-8-sig")
    names = (
        "WorktreeGoldenF11_MultiplePathsKeepOidAttribution",
        "WorktreeGoldenF11_MixedUntrackedSymlinkKeepsOidAttribution",
        "WorktreeGoldenF11_MixedTrackedStatesKeepOidAttribution",
    )
    # Fail closed on missing/renamed/duplicated test methods.
    offsets = []
    for name in names:
        if source.count("public async Task " + name) != 1:
            raise AssertionError(f"C# F11 test missing or duplicated: {name}")
        offsets.append(source.index("public async Task " + name))
    if offsets != sorted(offsets):
        raise AssertionError("C# F11 test layout changed; review extraction boundaries")

    multiple = source[offsets[0]:offsets[1]]
    actual_a = {
        "tracked_I": _csharp_constant(multiple, "expectedTrackedI"),
        "tracked_S": _csharp_constant(multiple, "expectedTrackedS"),
        "tracked_W": _csharp_constant(multiple, "expectedTrackedW"),
        "untracked_W": _csharp_constant(multiple, "expectedUntrackedW"),
    }
    # InlineData precede the method, so parse only the attributes immediately
    # before the correct method declaration; unexpected shapes fail closed.
    symlink_prefix = source[source.rfind("[LinuxOnlyTheory]", offsets[0], offsets[1]):offsets[1]]
    if not symlink_prefix.startswith("[LinuxOnlyTheory]"):
        raise AssertionError("C# F11 symlink attributes missing")
    links = re.findall(r'\[InlineData\("([^"]+)",\s*"(sha256:[0-9a-f]{64})"\)\]', symlink_prefix)
    if len(links) != 2 or {item[0] for item in links} != {"a.txt", "c.txt"}:
        raise AssertionError("C# symlink InlineData shape changed")
    actual_c = {"link_a_W" if target == "a.txt" else "link_c_W": value
                for target, value in links}

    between = source[offsets[1]:offsets[2]]
    theory_pos = between.rfind("[Theory]")
    if theory_pos < 0:
        raise AssertionError("C# mixed tracked Theory attributes missing")
    states = re.findall(r'\[InlineData\((true|false),\s*"(sha256:[0-9a-f]{64})"\)\]',
                        between[theory_pos:])
    if len(states) != 2 or {item[0] for item in states} != {"true", "false"}:
        raise AssertionError("C# mixed tracked InlineData shape changed")
    actual_b = {"directory_W" if flag == "true" else "missing_W": value
                for flag, value in states}
    actual_b["tracked_I"] = _csharp_constant(source[offsets[2]:], "expectedI")
    actual_b["tracked_S"] = _csharp_constant(source[offsets[2]:], "expectedS")

    for scenario, values in (("F11-A", actual_a), ("F11-B", actual_b), ("F11-C", actual_c)):
        for key, literal in values.items():
            value = results["tracked"]["I"] if key == "tracked_I" else (
                results["tracked"]["S"] if key == "tracked_S" else {
                    "tracked_W": results["tracked"]["W"],
                    "untracked_W": results["untracked"]["W"],
                    "missing_W": results["missing"]["W"],
                    "directory_W": results["directory"]["W"],
                    "link_a_W": results["link_a"]["W"],
                    "link_c_W": results["link_c"]["W"],
                }[key]
            )
            assert_equal(f"C# {scenario} {key}", literal, value)
    print("C# CROSS-CHECK: eight F11 W/I/S pins and mixed-state I/S pins match computed Python results")


def verify_real_git(*, require_symlink: bool = False) -> bool:
    """Use Git for independent object/index checks; return real-symlink coverage."""
    if shutil.which("git") is None:
        raise RuntimeError("Git is required to verify real repository fixtures")
    # Remove ALL inherited Git state before constructing isolated fixture repos.
    # In particular GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and GIT_CONFIG_COUNT
    # must never leak from the invoking shell into a temporary test repository.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    with tempfile.TemporaryDirectory(prefix="codelaxy-f11-oracle-") as tmp:
        root = Path(tmp)

        def run(*args: str, stdin: bytes | None = None) -> bytes:
            result = subprocess.run(
                ["git", "-c", "core.autocrlf=false", "-c", "core.filemode=false", *args],
                cwd=root, env=env, input=stdin,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                timeout=30,
            )
            if result.returncode:
                raise RuntimeError(f"git {args}: {result.stderr.decode('utf-8', 'replace')}")
            return result.stdout

        run("init", "-b", "main", "--object-format=sha1", "--template=")
        tree_oid = run(
            "hash-object", "-w", "-t", "tree", "--stdin", stdin=b""
        ).strip().decode("ascii")
        assert_equal("empty tree", tree_oid, git_object_oid("tree", b""))
        commit_oid = run(
            "hash-object", "-w", "-t", "commit", "--stdin", stdin=COMMIT_BYTES
        ).strip().decode("ascii")
        assert_equal("commit", commit_oid, git_object_oid("commit", COMMIT_BYTES))
        run("update-ref", "refs/heads/main", commit_oid)
        for path, content in CONTENT.items():
            (root / path).write_bytes(content)
        run("add", "--", *sorted(CONTENT))

        expected_index = b"".join(
            f"100644 {git_object_oid('blob', CONTENT[p])} 0\t{p}\0".encode("utf-8")
            for p in sorted(CONTENT)
        )
        assert_equal("real Git index", run("ls-files", "--stage", "-z"), expected_index)
        assert_equal("tracked HEAD", run("rev-parse", "HEAD").strip().decode(), commit_oid)
        (root / "b.txt").unlink()
        if (root / "b.txt").exists():
            raise AssertionError("tracked missing fixture not missing")
        (root / "b.txt").mkdir()
        if not (root / "b.txt").is_dir():
            raise AssertionError("tracked directory fixture not a directory")
        assert_equal(
            "index intact after conflict", run("ls-files", "--stage", "-z"), expected_index
        )
        if run("ls-files", "--others", "--exclude-per-directory=.gitignore", "-z"):
            raise AssertionError("unexpected untracked files in directory-conflict fixture")
        print("REAL GIT F11-B: tracked membership / empty directory conflict verified")

    # The reference for F11-C is platform-neutral, but physical symlink
    # creation is an OS capability and is not silently counted as a PASS.
    if os.name == "nt":
        if require_symlink:
            raise RuntimeError("F11-C real-Git symlink verification requires Unix")
        print("REAL GIT F11-C symlink: NOT VERIFIED on Windows")
        return False
    with tempfile.TemporaryDirectory(prefix="codelaxy-f11-symlink-") as tmp:
        root = Path(tmp)

        def git_untracked(*args: str, stdin: bytes | None = None) -> bytes:
            result = subprocess.run(
                ["git", "-c", "core.autocrlf=false", "-c", "core.filemode=false", *args],
                cwd=root, env=env, input=stdin,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            if result.returncode:
                raise RuntimeError(f"git {args}: {result.stderr.decode('utf-8', 'replace')}")
            return result.stdout

        git_untracked("init", "-b", "main", "--object-format=sha1", "--template=")
        # Write the referenced empty tree before storing a commit that names it.
        empty_tree = git_untracked("hash-object", "-w", "-t", "tree", "--stdin", stdin=b"")
        assert_equal("untracked empty tree", empty_tree.strip().decode("ascii"),
                     git_object_oid("tree", b""))
        # Set a deterministic HEAD without needing a local user identity.
        baseline = git_untracked("hash-object", "-w", "-t", "commit", "--stdin",
                                 stdin=COMMIT_BYTES).strip().decode("ascii")
        assert_equal("untracked HEAD", baseline, git_object_oid("commit", COMMIT_BYTES))
        git_untracked("update-ref", "refs/heads/main", baseline)
        for path in ("a.txt", "c.txt"):
            (root / path).write_bytes(CONTENT[path])
        expected_untracked_paths = b"a.txt\0b.link\0c.txt\0"
        (root / "b.link").symlink_to("a.txt")
        assert_equal("link target bytes", os.readlink(os.fsencode(root / "b.link")), b"a.txt")
        assert_equal(
            "real untracked Git path list (link a)",
            git_untracked("ls-files", "--others", "--exclude-per-directory=.gitignore", "-z"),
            expected_untracked_paths,
        )
        (root / "b.link").unlink()
        (root / "b.link").symlink_to("c.txt")
        assert_equal("retarget link bytes", os.readlink(os.fsencode(root / "b.link")), b"c.txt")
        assert_equal(
            "real untracked Git path list (link c)",
            git_untracked("ls-files", "--others", "--exclude-per-directory=.gitignore", "-z"),
            expected_untracked_paths,
        )
        print("REAL GIT F11-C: symlink and path membership verified")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csharp-tests", type=Path,
        default=Path(__file__).resolve().parent / "Codelaxy.Tests" / "GitSnapshotHeadStagedGoldenTests.cs",
        help="C# F11 Golden test source whose named literals must match Python",
    )
    parser.add_argument(
        "--require-real-symlink", action="store_true",
        help="Fail instead of treating Windows real-Git symlink verification as unavailable",
    )
    arguments = parser.parse_args()
    result = check_reference()
    check_csharp_contract(arguments.csharp_tests, result)
    symlink_verified = verify_real_git(require_symlink=arguments.require_real_symlink)
    if symlink_verified:
        print("PASS: F11 reference + C# pins + real Git symlink verified; no Codelaxy executed")
    else:
        print("PARTIAL PASS: Python reference + C# pins; real Git symlink NOT VERIFIED on Windows")
