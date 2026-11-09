"""IMP2-02 - record store, ID format, next-id and the check against a base ref (tier A for DE-01/DE-02/DE-06)."""
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from clxreg import canon, store


def rec(typ, num, **extra):
    d = {"schema_version": 1, "id": f"CLX-{typ}-{num:04d}", "type": typ, "title": "t"}
    d.update(extra)
    return d


def put(root, typ, num, obj=None, name=None):
    obj = rec(typ, num) if obj is None else obj
    d = Path(root) / "records" / typ
    d.mkdir(parents=True, exist_ok=True)
    p = d / (name or f"CLX-{typ}-{num:04d}.json")
    canon.write_record(p, obj, overwrite=True)
    return p


def new_root(tmp):
    for t in store.STORED_TYPES:
        (Path(tmp) / "records" / t).mkdir(parents=True, exist_ok=True)
    return Path(tmp)


def codes(findings):
    return sorted((f.code, f.record) for f in findings)


def only_codes(findings):
    return sorted({f.code for f in findings})


class IdFormatTests(unittest.TestCase):
    """Test vectors of ID-POLICY (phase 1, chapter 8) for the ID shape."""

    VALID = ["CLX-REQ-0001", "CLX-SCN-0042", "CLX-EVD-9999", "CLX-MIL-0003", "CLX-REQ-12345", "CLX-DEC-0001"]
    INVALID = ["CLX-REQ-1", "CLX-REQ-001", "clx-req-0001", "CLX-req-0001", "CLX-XYZ-0001", "CLX-REQ-0001 ", "CLX-REQ-0001\n",
               " CLX-REQ-0001", "CLX-REQ-", "CLX-REQ-00a1", "CLX-REQ-０００１", "XXX-REQ-0001", "CLX-REQ-0001.json", "CLX_REQ_0001", ""]

    def test_valid(self):
        for i in self.VALID:
            with self.subTest(i):
                self.assertIsNotNone(store.parse_id(i))

    def test_invalid(self):
        for i in self.INVALID:
            with self.subTest(repr(i)):
                self.assertIsNone(store.parse_id(i))

    def test_parse_returns_type_and_number(self):
        self.assertEqual(store.parse_id("CLX-SCN-0042"), ("SCN", 42))
        self.assertEqual(store.parse_id("CLX-REQ-12345"), ("REQ", 12345))

    def test_format_pads_to_four_digits_and_never_truncates(self):
        self.assertEqual(store.format_id("REQ", 1), "CLX-REQ-0001")
        self.assertEqual(store.format_id("EVD", 9999), "CLX-EVD-9999")
        self.assertEqual(store.format_id("EVD", 10000), "CLX-EVD-10000")
        with self.assertRaises(store.StoreError):
            store.format_id("REQ", 0)                 # 0000 is reserved for test vectors
        with self.assertRaises(store.StoreError):
            store.format_id("XYZ", 1)


class LoadTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = new_root(self._t.name)

    def test_clean_store_has_no_findings_and_loads_every_record(self):
        put(self.root, "REQ", 1)
        put(self.root, "REQ", 2)
        put(self.root, "SCN", 1)
        put(self.root, "MIL", 3)
        s = store.load(self.root)
        self.assertEqual(s.findings, [])
        self.assertEqual(sorted(s.records), ["CLX-MIL-0003", "CLX-REQ-0001", "CLX-REQ-0002", "CLX-SCN-0001"])
        self.assertEqual(s.records["CLX-REQ-0002"].obj["title"], "t")
        self.assertEqual(s.records["CLX-REQ-0002"].path, "records/REQ/CLX-REQ-0002.json")

    def test_empty_but_present_store_is_valid(self):
        s = store.load(self.root)
        self.assertEqual((s.records, s.findings), ({}, []))

    def test_missing_records_directory_is_an_error_not_an_empty_pass(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(store.StoreError):
                store.load(d)

    def test_missing_root_is_an_error(self):
        with self.assertRaises(store.StoreError):
            store.load(self.root / "nope")

    def test_file_name_must_be_a_valid_id(self):
        for name in ("CLX-REQ-1.json", "clx-req-0001.json", "CLX-REQ-0001.JSON", "CLX-REQ-0001.json.bak", "notes.json"):
            with self.subTest(name):
                put(self.root, "REQ", 1, name=name)
                s = store.load(self.root)
                self.assertIn("DE-02", only_codes(s.findings))
                (self.root / "records" / "REQ" / name).unlink()

    def test_directory_type_must_match_id_type(self):
        put(self.root, "REQ", 1, obj=rec("SCN", 1), name="CLX-SCN-0001.json")
        s = store.load(self.root)
        self.assertEqual(only_codes(s.findings), ["DE-02"])
        self.assertEqual(s.findings[0].record, "records/REQ/CLX-SCN-0001.json")

    def test_the_type_in_the_file_name_alone_is_enough_to_reject(self):
        put(self.root, "REQ", 1, obj=rec("SCN", 1, type="REQ"), name="CLX-SCN-0001.json")     # id == file name, type field == directory
        s = store.load(self.root)
        self.assertEqual(only_codes(s.findings), ["DE-02"])
        self.assertEqual(s.records, {})

    def test_decision_ids_do_not_live_in_the_record_store(self):
        put(self.root, "REQ", 1, obj=rec("DEC", 1), name="CLX-DEC-0001.json")
        self.assertIn("DE-02", only_codes(store.load(self.root).findings))

    def test_id_inside_must_equal_file_name(self):
        put(self.root, "REQ", 1, obj=rec("REQ", 2))
        self.assertIn("DE-02", only_codes(store.load(self.root).findings))

    def test_id_field_missing_or_not_a_string(self):
        for bad in ({"schema_version": 1, "type": "REQ", "title": "t"}, rec("REQ", 1, id=1)):
            with self.subTest(repr(bad)):
                put(self.root, "REQ", 1, obj=bad)
                self.assertIn("DE-02", only_codes(store.load(self.root).findings))

    def test_type_field_must_equal_directory(self):
        put(self.root, "REQ", 1, obj=rec("REQ", 1, type="SCN"))
        self.assertIn("DE-02", only_codes(store.load(self.root).findings))

    def test_schema_version_must_be_the_known_one(self):
        for v in (2, 0, "1", None, True):
            with self.subTest(repr(v)):
                put(self.root, "REQ", 1, obj=rec("REQ", 1, schema_version=v))
                self.assertIn("DE-02", only_codes(store.load(self.root).findings))
        o = rec("REQ", 1)
        del o["schema_version"]
        put(self.root, "REQ", 1, obj=o)
        self.assertIn("DE-02", only_codes(store.load(self.root).findings))

    def test_not_canonical_forms_are_data_errors(self):
        p = put(self.root, "REQ", 1)
        good = p.read_bytes()
        forms = {
            "crlf": good.replace(b"\n", b"\r\n"),
            "no trailing newline": good.rstrip(b"\n"),
            "bom": b"\xef\xbb\xbf" + good,
            "four space indent": canon.dumps(rec("REQ", 1)).replace("  ", "    ").encode("utf-8"),
            "unsorted keys": b'{\n  "type": "REQ",\n  "id": "CLX-REQ-0001",\n  "schema_version": 1,\n  "title": "t"\n}\n',
            "trailing spaces": good.replace(b",\n", b", \n", 1),
        }
        for name, raw in forms.items():
            with self.subTest(name):
                p.write_bytes(raw)
                self.assertIn("DE-02", only_codes(store.load(self.root).findings))

    def test_unreadable_content_is_a_data_error_not_a_crash(self):
        p = put(self.root, "REQ", 1)
        for name, raw in {"invalid json": b"{not json", "array": b"[]\n", "scalar": b"1\n", "empty": b"", "not utf-8": b"\xff\xfe\x00{}",
                          "float": b'{"id": "CLX-REQ-0001", "n": 1.5}\n', "duplicate keys": b'{"a": 1, "a": 2}\n'}.items():
            with self.subTest(name):
                p.write_bytes(raw)
                s = store.load(self.root)
                self.assertEqual(only_codes(s.findings), ["DE-02"])
                self.assertEqual(s.records, {})

    def test_stray_entries_are_reported(self):
        put(self.root, "REQ", 1)
        (self.root / "records" / "REQ" / "README.md").write_text("x", encoding="utf-8")
        (self.root / "records" / "stray.json").write_text("{}\n", encoding="utf-8")
        (self.root / "records" / "FOO").mkdir()
        (self.root / "records" / "FOO" / "CLX-REQ-0009.json").write_text("{}\n", encoding="utf-8")
        (self.root / "records" / "SCN" / "nested").mkdir()
        (self.root / "records" / "SCN" / "nested" / "CLX-SCN-0001.json").write_text("{}\n", encoding="utf-8")
        s = store.load(self.root)
        paths = {f.record for f in s.findings}
        self.assertEqual(only_codes(s.findings), ["DE-02"])
        self.assertEqual(paths, {"records/REQ/README.md", "records/stray.json", "records/FOO", "records/SCN/nested"})
        self.assertIn("subdirector", next(f.message for f in s.findings if f.record == "records/SCN/nested"))

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlink support")
    def test_symlinked_record_is_refused_even_when_its_content_is_perfect(self):
        target = self.root / "outside.json"
        canon.write_record(target, rec("REQ", 2))
        link = self.root / "records" / "REQ" / "CLX-REQ-0002.json"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted here")
        s = store.load(self.root)
        self.assertEqual(codes(s.findings), [("DE-02", "records/REQ/CLX-REQ-0002.json")])
        self.assertIn("symbolic", s.findings[0].message)
        self.assertEqual(s.records, {})

    def test_same_id_in_two_files_is_de01_on_both_files(self):
        put(self.root, "REQ", 1)
        put(self.root, "REQ", 1, name="CLX-REQ-0001-copy.json")
        s = store.load(self.root)
        de01 = [f for f in s.findings if f.code == "DE-01"]
        self.assertEqual(sorted(f.record for f in de01), ["records/REQ/CLX-REQ-0001-copy.json", "records/REQ/CLX-REQ-0001.json"])
        self.assertIn("DE-02", only_codes(s.findings))     # the copy also has a wrong file name
        self.assertNotIn("CLX-REQ-0001", s.records)        # a duplicated id has no winner: neither file is loaded

    def test_same_id_across_directories_is_de01(self):
        put(self.root, "REQ", 1)
        put(self.root, "SCN", 1, obj=rec("REQ", 1), name="CLX-REQ-0001.json")
        self.assertIn("DE-01", only_codes(store.load(self.root).findings))

    def test_same_number_in_different_types_is_fine(self):
        put(self.root, "REQ", 7)
        put(self.root, "SCN", 7)
        put(self.root, "EVD", 7)
        self.assertEqual(store.load(self.root).findings, [])

    def test_findings_and_order_are_deterministic(self):
        for n in (5, 3, 9):
            put(self.root, "REQ", n)
        put(self.root, "REQ", 4, obj=rec("REQ", 40))
        put(self.root, "SCN", 1, obj={"x": 1})
        put(self.root, "EVD", 1)
        put(self.root, "SCN", 2, obj=rec("EVD", 1), name="CLX-EVD-0001.json")      # same id in another directory: DE-01 is found after the scan
        a = store.load(self.root)
        b = store.load(self.root)
        self.assertEqual([f.line() for f in a.findings], [f.line() for f in b.findings])
        self.assertEqual(list(a.records), sorted(a.records))
        self.assertEqual([f.record for f in a.findings], sorted(f.record for f in a.findings))

    def test_loading_never_modifies_files(self):
        p = put(self.root, "REQ", 1)
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        before = {x: x.read_bytes() for x in (self.root / "records").rglob("*") if x.is_file()}
        store.load(self.root)
        self.assertEqual(before, {x: x.read_bytes() for x in (self.root / "records").rglob("*") if x.is_file()})


class NextIdTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = new_root(self._t.name)

    def test_first_id_is_0001_never_0000(self):
        self.assertEqual(store.next_id(self.root, "REQ"), "CLX-REQ-0001")

    def test_zero_vector_file_does_not_make_the_next_one_0000(self):
        put(self.root, "REQ", 0)
        self.assertEqual(store.next_id(self.root, "REQ"), "CLX-REQ-0001")

    def test_max_plus_one_and_gaps_are_not_filled(self):
        for n in (1, 2, 5):
            put(self.root, "REQ", n)
        self.assertEqual(store.next_id(self.root, "REQ"), "CLX-REQ-0006")

    def test_numbering_is_per_type(self):
        put(self.root, "REQ", 9)
        put(self.root, "SCN", 2)
        self.assertEqual(store.next_id(self.root, "SCN"), "CLX-SCN-0003")
        self.assertEqual(store.next_id(self.root, "EVD"), "CLX-EVD-0001")
        self.assertEqual(store.next_id(self.root, "MIL"), "CLX-MIL-0001")

    def test_withdrawn_and_superseded_records_still_count(self):
        put(self.root, "REQ", 1)
        put(self.root, "REQ", 2, obj=rec("REQ", 2, lifecycle="WITHDRAWN"))
        put(self.root, "REQ", 3, obj=rec("REQ", 3, lifecycle="SUPERSEDED"))
        self.assertEqual(store.next_id(self.root, "REQ"), "CLX-REQ-0004")

    def test_broken_or_misnamed_files_still_reserve_their_number(self):
        (self.root / "records" / "REQ" / "CLX-REQ-0007.json").write_bytes(b"{not json")
        (self.root / "records" / "REQ" / "CLX-REQ-8.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(store.next_id(self.root, "REQ"), "CLX-REQ-0009")

    def test_a_misplaced_file_still_reserves_its_number(self):
        (self.root / "records" / "SCN" / "CLX-REQ-0050.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(store.next_id(self.root, "REQ"), "CLX-REQ-0051")
        self.assertEqual(store.next_id(self.root, "SCN"), "CLX-SCN-0001")

    def test_number_grows_past_four_digits(self):
        put(self.root, "REQ", 9999)
        self.assertEqual(store.next_id(self.root, "REQ"), "CLX-REQ-10000")

    def test_unknown_type_is_an_error(self):
        for t in ("XYZ", "DEC", "req", ""):
            with self.subTest(t):
                with self.assertRaises(store.StoreError):
                    store.next_id(self.root, t)

    def test_is_read_only(self):
        put(self.root, "REQ", 1)
        before = sorted(str(x) for x in self.root.rglob("*"))
        store.next_id(self.root, "REQ")
        self.assertEqual(before, sorted(str(x) for x in self.root.rglob("*")))


# --- tests that need a real git repository --------------------------------------------------------------------------------------
def git(repo, *args, check=True):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
                        "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", env=env)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {p.stdout}{p.stderr}")
    return p


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


class GitCase(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.repo = Path(self._t.name)
        git(self.repo, "init", "-q", "-b", "main")
        new_root(self.repo)
        put(self.repo, "REQ", 1)
        put(self.repo, "REQ", 2)
        put(self.repo, "SCN", 1)
        (self.repo / "README.md").write_text("r\n", encoding="utf-8")
        commit_all(self.repo, "base")
        self.base = git(self.repo, "rev-parse", "HEAD").stdout.strip()


class BaseCheckTests(GitCase):
    def test_unchanged_tree_has_no_findings(self):
        self.assertEqual(store.check_against_base(self.repo, "HEAD"), [])

    def test_added_record_is_fine_even_when_untracked_or_committed(self):
        put(self.repo, "REQ", 3)
        self.assertEqual(store.check_against_base(self.repo, self.base), [])
        commit_all(self.repo, "add")
        self.assertEqual(store.check_against_base(self.repo, self.base), [])

    def test_modified_record_with_same_id_is_fine(self):
        put(self.repo, "REQ", 1, obj=rec("REQ", 1, title="new title"))
        self.assertEqual(store.check_against_base(self.repo, self.base), [])

    def test_deleted_record_is_de06_whether_committed_unstaged_or_staged(self):
        p = self.repo / "records" / "REQ" / "CLX-REQ-0002.json"
        p.unlink()                                                   # unstaged deletion
        f = store.check_against_base(self.repo, self.base)
        self.assertEqual(codes(f), [("DE-06", "records/REQ/CLX-REQ-0002.json")])
        git(self.repo, "add", "-A")                                  # staged deletion
        self.assertEqual(only_codes(store.check_against_base(self.repo, self.base)), ["DE-06"])
        git(self.repo, "commit", "-q", "-m", "delete")               # committed deletion
        self.assertEqual(only_codes(store.check_against_base(self.repo, self.base)), ["DE-06"])

    def test_renamed_record_is_de06_for_the_old_path(self):
        src = self.repo / "records" / "REQ" / "CLX-REQ-0002.json"
        src.rename(self.repo / "records" / "REQ" / "CLX-REQ-0020.json")
        commit_all(self.repo, "rename")
        f = store.check_against_base(self.repo, self.base)
        self.assertIn(("DE-06", "records/REQ/CLX-REQ-0002.json"), codes(f))

    def test_changed_id_inside_an_existing_file_is_de06(self):
        put(self.repo, "REQ", 1, obj=rec("REQ", 1, id="CLX-REQ-0099"), name="CLX-REQ-0001.json")
        f = store.check_against_base(self.repo, self.base)
        self.assertIn(("DE-06", "records/REQ/CLX-REQ-0001.json"), codes(f))

    def test_deleted_file_outside_records_is_not_our_business(self):
        (self.repo / "README.md").unlink()
        self.assertEqual(store.check_against_base(self.repo, self.base), [])

    def test_base_without_records_means_nothing_to_protect(self):
        git(self.repo, "checkout", "-q", "--orphan", "bare")
        git(self.repo, "rm", "-rq", "--cached", ".")
        for x in ("records", "README.md"):
            p = self.repo / x
            if p.is_dir():
                import shutil
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
        (self.repo / "other.txt").write_text("o\n", encoding="utf-8")
        commit_all(self.repo, "no records")
        empty = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        new_root(self.repo)
        put(self.repo, "REQ", 1)
        self.assertEqual(store.check_against_base(self.repo, empty), [])

    def test_bad_refs_are_errors_not_passes(self):
        for ref in ("no-such-ref", "", "--output=x", "-h", "HEAD~99", "a" * 40):
            with self.subTest(repr(ref)):
                with self.assertRaises(store.StoreError):
                    store.check_against_base(self.repo, ref)

    def test_unexpected_git_output_is_an_error_not_a_pass(self):
        real = store._git

        def fake(code, stdout=b"", stderr=b""):
            def run(root, *args):
                if args[0] == "diff":
                    return subprocess.CompletedProcess(args, code, stdout, stderr)
                return real(root, *args)
            return run

        for name, f in {"git diff fails": fake(1, stderr=b"boom"), "odd number of fields": fake(0, stdout=b"D\0")}.items():
            with self.subTest(name):
                store._git = f
                try:
                    with self.assertRaises(store.StoreError):
                        store.check_against_base(self.repo, self.base)
                finally:
                    store._git = real

    def test_not_a_git_repository_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            new_root(d)
            with self.assertRaises(store.StoreError):
                store.check_against_base(d, "HEAD")

    def test_registry_in_a_subdirectory_of_the_repository(self):
        sub = self.repo / "registry"
        sub.mkdir()
        for t in store.STORED_TYPES:
            (sub / "records" / t).mkdir(parents=True)
        put(sub, "REQ", 5)
        commit_all(self.repo, "sub")
        base = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(store.check_against_base(sub, base), [])
        (sub / "records" / "REQ" / "CLX-REQ-0005.json").unlink()
        self.assertEqual(codes(store.check_against_base(sub, base)), [("DE-06", "records/REQ/CLX-REQ-0005.json")])

    def test_does_not_stage_or_modify_anything(self):
        put(self.repo, "REQ", 3)
        (self.repo / "records" / "REQ" / "CLX-REQ-0002.json").unlink()
        before = git(self.repo, "status", "--porcelain").stdout
        store.check_against_base(self.repo, self.base)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, before)


class BaseIdsTests(GitCase):
    def test_next_id_considers_ids_that_exist_only_in_the_base(self):
        put(self.repo, "REQ", 7)
        commit_all(self.repo, "7")
        high = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        (self.repo / "records" / "REQ" / "CLX-REQ-0007.json").unlink()      # branch that (wrongly) deleted it
        self.assertEqual(store.next_id(self.repo, "REQ"), "CLX-REQ-0003")
        self.assertEqual(store.next_id(self.repo, "REQ", base=high), "CLX-REQ-0008")

    def test_numbers_of_other_types_in_the_base_do_not_count(self):
        put(self.repo, "SCN", 50)
        commit_all(self.repo, "scn 50")
        high = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(store.next_id(self.repo, "REQ", base=high), "CLX-REQ-0003")
        self.assertEqual(store.next_id(self.repo, "SCN", base=high), "CLX-SCN-0051")

    def test_next_id_with_bad_base_is_an_error(self):
        with self.assertRaises(store.StoreError):
            store.next_id(self.repo, "REQ", base="nope")

    def test_parallel_branches_that_take_the_same_number_conflict_on_the_path(self):
        git(self.repo, "checkout", "-q", "-b", "a")
        self.assertEqual(store.next_id(self.repo, "REQ"), "CLX-REQ-0003")
        put(self.repo, "REQ", 3, obj=rec("REQ", 3, title="from a"))
        commit_all(self.repo, "a")
        git(self.repo, "checkout", "-q", "-b", "b", self.base)
        self.assertEqual(store.next_id(self.repo, "REQ"), "CLX-REQ-0003")   # same number on the other branch
        put(self.repo, "REQ", 3, obj=rec("REQ", 3, title="from b"))
        commit_all(self.repo, "b")
        merge = git(self.repo, "merge", "--no-edit", "a", check=False)
        self.assertNotEqual(merge.returncode, 0, "two branches taking the same ID must not merge silently")
        self.assertIn("CLX-REQ-0003.json", merge.stdout + merge.stderr)
        git(self.repo, "merge", "--abort")


class CliTests(GitCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = store.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_ok(self):
        code, out, _ = self.run_cli("check", "--root", str(self.repo))
        self.assertEqual(code, 0, out)
        self.assertIn("records: 3", out)

    def test_check_reports_data_errors_with_exit_1(self):
        put(self.repo, "REQ", 1, obj=rec("REQ", 9))
        code, out, _ = self.run_cli("check", "--root", str(self.repo))
        self.assertEqual(code, 1)
        self.assertIn("DE-02", out)

    def test_check_with_base_finds_deletion(self):
        (self.repo / "records" / "REQ" / "CLX-REQ-0001.json").unlink()
        code, out, _ = self.run_cli("check", "--root", str(self.repo), "--base", self.base)
        self.assertEqual(code, 1)
        self.assertIn("DE-06", out)

    def test_usage_and_environment_problems_exit_3(self):
        self.assertEqual(self.run_cli("check", "--root", str(self.repo / "nope"))[0], 3)
        self.assertEqual(self.run_cli("check", "--root", str(self.repo), "--base", "nope")[0], 3)
        self.assertEqual(self.run_cli("next-id", "XYZ", "--root", str(self.repo))[0], 3)

    def test_next_id_prints_only_the_id(self):
        code, out, _ = self.run_cli("next-id", "REQ", "--root", str(self.repo))
        self.assertEqual((code, out), (0, "CLX-REQ-0003\n"))
        code, out, _ = self.run_cli("next-id", "REQ", "--root", str(self.repo), "--base", self.base)
        self.assertEqual((code, out), (0, "CLX-REQ-0003\n"))


if __name__ == "__main__":
    unittest.main()
