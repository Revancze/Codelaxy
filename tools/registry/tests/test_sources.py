"""IMP2-04 - source catalog: pinning, verification against disk, literal quotes (DE-13), status transitions (tier A for DE-13)."""
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from clxreg import canon, sources
from clxreg.findings import ADVISORY, DATA_ERROR, blocking

HERE = Path(__file__).resolve().parent
LOCAL = HERE.parent / "local"

FILES = {
    "r1.md": b"The owner ratified revision 2 on 2026-10-25.\n",
    "v1.md": b"Revision 1 text.\nRT-less.\n",
    "v2.md": b"Status: **Not ratified.** Draft.\nRT1\xe2\x80\x93RT3 are the resolver test gaps.\nCommon sentence.\n",
    "v2m.md": b"Status: **RATIFIED** by the owner.\nRT1\xe2\x80\x93RT3 are the resolver test gaps.\nCommon sentence.\n",
    "v3.md": b"Revision 3 draft.\n",
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def ver(vid, status, data=None, pinning="sha256-only", root="ws", path=None, **extra):
    data = FILES[f"{vid}.md"] if data is None else data
    v = {"id": vid, "sha256": sha(data), "bytes": len(data), "pinning": pinning, "status": status,
         "location": {"root": root, "path": path or f"{vid}.md"}}
    if pinning == "git-blob":
        v.update(git_blob="a" * 40, commit="b" * 40)
    v.update(extra)
    return v


RB = {"source": "ratification", "version": "r1"}


def good_catalog():
    return {"schema": sources.SCHEMA, "sources": [
        {"key": "ratification", "title": "Ratification record", "category": "RATIFIED", "subtype": "RATIFICATION-RECORD",
         "versions": [ver("r1", "RATIFIED")]},
        {"key": "doc", "title": "The document", "category": "RATIFIED",
         "versions": [ver("v1", "HISTORICAL"), ver("v2", "RATIFIED", ratified_by=RB), ver("v2m", "RATIFIED-MARKED", ratified_by=RB),
                      ver("v3", "DRAFT")]},
    ]}


def S(cat, key):
    return next(s for s in cat["sources"] if s["key"] == key)


def V(cat, key, vid):
    return next(v for v in S(cat, key)["versions"] if v["id"] == vid)


def codes(findings):
    return sorted((f.code, f.record) for f in findings)


def only(findings):
    return sorted({f.code for f in findings})


class Workspace(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.ws = Path(self._t.name) / "ws"
        self.ws.mkdir()
        for name, data in FILES.items():
            (self.ws / name).write_bytes(data)
        self.roots = {"ws": str(self.ws)}
        self.cat = good_catalog()


class ValidateTests(Workspace):
    def test_good_catalog_has_no_findings(self):
        self.assertEqual(sources.validate_catalog(self.cat), [])

    def test_top_level(self):
        for bad in ([], "x", None, {"schema": sources.SCHEMA}, {"sources": []}, {"schema": "other", "sources": []},
                    {"schema": sources.SCHEMA, "sources": {}}, {"schema": sources.SCHEMA, "sources": [], "extra": 1}):
            with self.subTest(repr(bad)):
                self.assertEqual(only(sources.validate_catalog(bad)), ["DE-02"])

    def test_source_fields_are_a_closed_set(self):
        for mutate in (lambda s: s.pop("title"), lambda s: s.pop("category"), lambda s: s.pop("versions"), lambda s: s.update(extra=1),
                       lambda s: s.update(title=1), lambda s: s.update(category="ratified"), lambda s: s.update(category="HEARSAY"),
                       lambda s: s.update(subtype="NOTES"), lambda s: s.update(key="Doc"), lambda s: s.update(key="a b"),
                       lambda s: s.update(key=""), lambda s: s.update(versions=[]), lambda s: s.update(versions={}),
                       lambda s: s.update(default_namespaces="x"), lambda s: s.update(default_namespaces=[1])):
            c = copy.deepcopy(self.cat)
            mutate(S(c, "doc"))
            with self.subTest():
                self.assertIn("DE-02", only(sources.validate_catalog(c)))

    def test_allowed_optional_source_fields(self):
        S(self.cat, "doc")["default_namespaces"] = ["micromap-resolver-gaps"]
        S(self.cat, "doc")["subtype"] = "PLANNING-VIEW"
        self.assertEqual(sources.validate_catalog(self.cat), [])

    def test_all_categories_and_subtypes_are_accepted_when_consistent(self):
        for cat in ("DRAFT", "HISTORICAL", "EXPERIMENTAL", "EVIDENCE"):
            c = copy.deepcopy(self.cat)
            c["sources"].append({"key": "x", "title": "x", "category": cat, "versions": [ver("v3", "DRAFT")]})
            with self.subTest(cat):
                self.assertEqual(sources.validate_catalog(c), [])
        for sub in ("RATIFICATION-RECORD", "PLANNING-VIEW", "GENERATED", "AUDIT-EVIDENCE"):
            c = copy.deepcopy(self.cat)
            c["sources"].append({"key": "x", "title": "x", "category": "EVIDENCE", "subtype": sub, "versions": [ver("v3", "DRAFT")]})
            with self.subTest(sub):
                self.assertEqual(sources.validate_catalog(c), [])

    def test_duplicate_source_key_and_duplicate_version_id(self):
        c = copy.deepcopy(self.cat)
        c["sources"].append(copy.deepcopy(S(c, "doc")))
        self.assertIn("DE-01", only(sources.validate_catalog(c)))
        c = copy.deepcopy(self.cat)
        S(c, "doc")["versions"].append(copy.deepcopy(V(c, "doc", "v3")))
        f = sources.validate_catalog(c)
        self.assertEqual([(x.code, x.record) for x in f if x.code == "DE-01"], [("DE-01", "sources:doc/v3")] * 2)

    def test_version_fields(self):
        base = ver("v3", "DRAFT")
        bad = {
            "no sha": lambda v: v.pop("sha256"), "short sha": lambda v: v.update(sha256="ab" * 31), "upper sha": lambda v: v.update(sha256="AB" * 32),
            "non hex": lambda v: v.update(sha256="zz" * 32), "sha as int": lambda v: v.update(sha256=1),
            "no bytes": lambda v: v.pop("bytes"), "negative bytes": lambda v: v.update(bytes=-1), "bool bytes": lambda v: v.update(bytes=True),
            "str bytes": lambda v: v.update(bytes="3"), "bad pinning": lambda v: v.update(pinning="trust-me"),
            "no pinning": lambda v: v.pop("pinning"), "bad status": lambda v: v.update(status="FINAL"), "no status": lambda v: v.pop("status"),
            "no location": lambda v: v.pop("location"), "unknown field": lambda v: v.update(extra=1), "bad id": lambda v: v.update(id="V 3"),
            "empty id": lambda v: v.update(id=""), "location extra": lambda v: v["location"].update(x=1),
            "location no root": lambda v: v["location"].pop("root"), "location no path": lambda v: v["location"].pop("path"),
            "root upper": lambda v: v["location"].update(root="WS"), "path absolute": lambda v: v["location"].update(path="/etc/x"),
            "path dotdot": lambda v: v["location"].update(path="a/../b"), "path leading dotdot": lambda v: v["location"].update(path="../b"),
            "path backslash": lambda v: v["location"].update(path="a\\b.md"), "path drive": lambda v: v["location"].update(path="C:/x.md"),
            "path empty segment": lambda v: v["location"].update(path="a//b.md"), "path empty": lambda v: v["location"].update(path=""),
            "path nul": lambda v: v["location"].update(path="a\0b.md"),
            "path dot segment": lambda v: v["location"].update(path="./b.md"), "path trailing slash": lambda v: v["location"].update(path="a/"),
            "sha256-only with git_blob": lambda v: v.update(git_blob="a" * 40),
            "note not str": lambda v: v.update(note=1),
        }
        for name, mutate in bad.items():
            c = copy.deepcopy(self.cat)
            S(c, "doc")["versions"][-1] = copy.deepcopy(base)
            mutate(S(c, "doc")["versions"][-1])
            with self.subTest(name):
                self.assertIn("DE-02", only(sources.validate_catalog(c)))

    def test_git_blob_pinning_needs_blob_and_commit_of_the_right_shape(self):
        for name, mutate in {"no blob": lambda v: v.pop("git_blob"), "no commit": lambda v: v.pop("commit"),
                             "short blob": lambda v: v.update(git_blob="a" * 39), "long commit": lambda v: v.update(commit="b" * 41),
                             "upper": lambda v: v.update(commit="B" * 40), "sha256 length ok": None}.items():
            c = copy.deepcopy(self.cat)
            v = ver("v3", "DRAFT", pinning="git-blob")
            S(c, "doc")["versions"][-1] = v
            if mutate:
                mutate(v)
                with self.subTest(name):
                    self.assertIn("DE-02", only(sources.validate_catalog(c)))
            else:
                v.update(git_blob="a" * 64, commit="b" * 64)
                self.assertEqual(sources.validate_catalog(c), [])

    def test_an_empty_source_file_is_a_valid_version(self):
        c = copy.deepcopy(self.cat)
        S(c, "doc")["versions"].append(ver("v4", "DRAFT", data=b"", path="v4.md"))
        self.assertEqual(sources.validate_catalog(c), [])

    def test_optional_note_is_accepted(self):
        V(self.cat, "doc", "v3")["note"] = "free text"
        self.assertEqual(sources.validate_catalog(self.cat), [])

    def test_ratified_status_needs_a_ratified_by_that_resolves_to_a_ratification_record(self):
        c = copy.deepcopy(self.cat)
        del V(c, "doc", "v2")["ratified_by"]
        self.assertEqual(codes(sources.validate_catalog(c)), [("DE-13", "sources:doc/v2")])
        c = copy.deepcopy(self.cat)
        del V(c, "doc", "v2m")["ratified_by"]
        self.assertEqual(codes(sources.validate_catalog(c)), [("DE-13", "sources:doc/v2m")])
        for ref, code in [({"source": "nope", "version": "r1"}, "DE-03"), ({"source": "ratification", "version": "nope"}, "DE-03"),
                          ({"source": "doc", "version": "v1"}, "DE-13"), ({"source": "doc", "version": "v2"}, "DE-13")]:
            c = copy.deepcopy(self.cat)
            V(c, "doc", "v2")["ratified_by"] = ref
            with self.subTest(ref):
                self.assertEqual(codes(sources.validate_catalog(c)), [(code, "sources:doc/v2")])

    def test_a_draft_record_cannot_ratify(self):
        c = copy.deepcopy(self.cat)
        S(c, "ratification")["versions"].append(ver("v3", "DRAFT"))
        V(c, "doc", "v2")["ratified_by"] = {"source": "ratification", "version": "v3"}
        self.assertEqual(codes(sources.validate_catalog(c)), [("DE-13", "sources:doc/v2")])

    def test_ratified_by_shape(self):
        for bad in ("CLX-DEC-0001", {"source": "ratification"}, {"source": "ratification", "version": "r1", "x": 1}, {"source": 1, "version": "r1"}, []):
            c = copy.deepcopy(self.cat)
            V(c, "doc", "v2")["ratified_by"] = bad
            with self.subTest(repr(bad)):
                self.assertIn("DE-02", only(sources.validate_catalog(c)))

    def test_ratified_by_on_a_non_ratified_version_is_rejected(self):
        for st in ("DRAFT", "HISTORICAL"):
            c = copy.deepcopy(self.cat)
            V(c, "doc", "v3")["status"] = st
            V(c, "doc", "v3")["ratified_by"] = RB
            with self.subTest(st):
                self.assertEqual(codes(sources.validate_catalog(c)), [("DE-13", "sources:doc/v3")])

    def test_a_ratification_record_does_not_ratify_itself(self):
        c = copy.deepcopy(self.cat)
        V(c, "ratification", "r1")["ratified_by"] = RB
        self.assertEqual(codes(sources.validate_catalog(c)), [("DE-13", "sources:ratification/r1")])

    def test_ratified_statuses_exist_only_in_a_ratified_category(self):
        for cat in ("DRAFT", "HISTORICAL", "EXPERIMENTAL", "EVIDENCE"):
            c = copy.deepcopy(self.cat)
            S(c, "doc")["category"] = cat
            with self.subTest(cat):
                self.assertIn(("DE-13", "sources:doc"), codes(sources.validate_catalog(c)))

    def test_ratified_category_needs_a_ratified_version(self):
        c = copy.deepcopy(self.cat)
        S(c, "doc")["versions"] = [ver("v1", "HISTORICAL"), ver("v3", "DRAFT")]
        self.assertEqual(codes(sources.validate_catalog(c)), [("DE-13", "sources:doc")])

    def test_findings_are_sorted_and_deterministic(self):
        c = copy.deepcopy(self.cat)
        V(c, "doc", "v3")["sha256"] = "x"
        V(c, "doc", "v1")["status"] = "FINAL"
        S(c, "ratification")["title"] = 1
        a, b = sources.validate_catalog(c), sources.validate_catalog(copy.deepcopy(c))
        self.assertEqual([f.line() for f in a], [f.line() for f in b])
        self.assertEqual([f.record for f in a], sorted(f.record for f in a))

    def test_validate_never_modifies_its_input(self):
        c = copy.deepcopy(self.cat)
        V(c, "doc", "v2")["ratified_by"] = {"source": "nope", "version": "r1"}
        before = copy.deepcopy(c)
        sources.validate_catalog(c)
        self.assertEqual(c, before)


class LoadTests(Workspace):
    def write(self, text):
        p = Path(self._t.name) / "sources.json"
        p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return p

    def test_load_good_canonical_file(self):
        obj, f = sources.load_catalog(self.write(canon.dumps(self.cat)))
        self.assertEqual((obj, f), (self.cat, []))

    def test_not_canonical_is_de02_but_the_object_is_returned(self):
        obj, f = sources.load_catalog(self.write(json.dumps(self.cat, indent=4)))
        self.assertEqual(obj, self.cat)
        self.assertEqual(only(f), ["DE-02"])

    def test_unreadable_content_is_de02_and_no_object(self):
        for raw in (b"{nope", b"\xff\xfe", b'{"a": 1, "a": 2}', b'{"a": 1.5}', b""):
            with self.subTest(raw):
                obj, f = sources.load_catalog(self.write(raw))
                self.assertIsNone(obj)
                self.assertEqual(only(f), ["DE-02"])

    def test_missing_file_is_an_environment_error(self):
        with self.assertRaises(sources.SourceError):
            sources.load_catalog(Path(self._t.name) / "absent.json")


class VerifyFilesTests(Workspace):
    def test_all_files_match(self):
        f = sources.verify_files(self.cat, self.roots)
        self.assertFalse(blocking(f))
        self.assertEqual({x.code for x in f}, {"AD-04"})                      # every version here is sha256-only
        self.assertEqual(len(f), 5)

    def test_git_blob_pinning_has_no_weak_pinning_advisory(self):
        c = copy.deepcopy(self.cat)
        for s in c["sources"]:
            for v in s["versions"]:
                v["pinning"] = "git-blob"
                v.update(git_blob="a" * 40, commit="b" * 40)
        self.assertEqual(sources.verify_files(c, self.roots), [])

    def test_changed_byte_is_de13_naming_the_version(self):
        p = self.ws / "v2.md"
        p.write_bytes(p.read_bytes().replace(b"Draft", b"Dr4ft"))
        f = sources.verify_files(self.cat, self.roots)
        self.assertEqual([(x.code, x.record) for x in f if x.code == "DE-13"], [("DE-13", "sources:doc/v2")])
        self.assertTrue(blocking(f))

    def test_same_size_different_content_is_still_caught(self):
        (self.ws / "v3.md").write_bytes(b"X" * len(FILES["v3.md"]))
        self.assertEqual([(x.code, x.record) for x in sources.verify_files(self.cat, self.roots) if x.cls == DATA_ERROR],
                         [("DE-13", "sources:doc/v3")])

    def test_wrong_size_in_the_catalog_is_de13_even_if_the_hash_matches(self):
        V(self.cat, "doc", "v3")["bytes"] += 1
        self.assertEqual([(x.code, x.record) for x in sources.verify_files(self.cat, self.roots) if x.cls == DATA_ERROR],
                         [("DE-13", "sources:doc/v3")])

    def test_missing_file_is_advisory_not_an_error(self):
        (self.ws / "v3.md").unlink()
        f = sources.verify_files(self.cat, self.roots)
        self.assertFalse(blocking(f))
        self.assertTrue(any(x.code == "AD-04" and x.record == "sources:doc/v3" and "not available" in x.message for x in f))

    def test_unconfigured_root_is_advisory_for_every_version_using_it(self):
        f = sources.verify_files(self.cat, {})
        self.assertFalse(blocking(f))
        self.assertEqual(len([x for x in f if "not available" in x.message]), 5)

    def test_a_directory_in_place_of_the_file_is_an_error(self):
        (self.ws / "v3.md").unlink()
        (self.ws / "v3.md").mkdir()
        self.assertEqual([(x.code, x.record) for x in sources.verify_files(self.cat, self.roots) if x.cls == DATA_ERROR],
                         [("DE-13", "sources:doc/v3")])

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlink support")
    def test_a_location_that_escapes_its_root_is_refused(self):
        outside = Path(self._t.name) / "outside.md"
        outside.write_bytes(FILES["v3.md"])
        try:
            os.symlink(outside, self.ws / "link.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted here")
        V(self.cat, "doc", "v3")["location"]["path"] = "link.md"
        self.assertEqual([(x.code, x.record) for x in sources.verify_files(self.cat, self.roots) if x.cls == DATA_ERROR],
                         [("DE-02", "sources:doc/v3")])

    def test_verification_never_modifies_the_sources(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.ws.iterdir()}
        sources.verify_files(self.cat, self.roots)
        sources.check_quote(self.cat, self.roots, {"source": "doc", "version": "v2", "quote": "Common sentence."})
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.ws.iterdir()})


class QuoteTests(Workspace):
    def q(self, version, quote, source="doc"):
        return sources.check_quote(self.cat, self.roots, {"source": source, "version": version, "quote": quote})

    def test_quote_present_in_both_versions(self):
        self.assertEqual(self.q("v2", "Common sentence."), [])
        self.assertEqual(self.q("v2m", "Common sentence."), [])

    def test_quote_present_in_only_one_version(self):
        self.assertEqual(self.q("v2", "**Not ratified.**"), [])
        self.assertEqual(codes(self.q("v2m", "**Not ratified.**")), [("DE-13", "sources:doc/v2m")])
        self.assertEqual(self.q("v2m", "**RATIFIED** by the owner."), [])
        self.assertEqual(codes(self.q("v2", "**RATIFIED** by the owner.")), [("DE-13", "sources:doc/v2")])

    def test_paraphrase_and_normalised_text_are_not_quotes(self):
        for quote in ("common sentence.", "Common  sentence.", "RT1-RT3 are the resolver test gaps.", "Common sentence. "):
            with self.subTest(quote):
                self.assertEqual(only(self.q("v2", quote)), ["DE-13"])

    def test_changed_byte_makes_the_source_untrusted_even_if_the_quote_is_still_there(self):
        p = self.ws / "v2.md"
        p.write_bytes(p.read_bytes().replace(b"Draft", b"Dr4ft"))
        f = self.q("v2", "Common sentence.")
        self.assertEqual(only(f), ["DE-13"])
        self.assertIn("pinned", f[0].message)

    def test_source_missing_from_disk_skips_the_check_with_ad04(self):
        (self.ws / "v2.md").unlink()
        f = self.q("v2", "Common sentence.")
        self.assertEqual([(x.cls, x.code) for x in f], [(ADVISORY, "AD-04")])
        self.assertFalse(blocking(f))

    def test_unknown_source_or_version_is_de03(self):
        self.assertEqual(only(self.q("v2", "x", source="nope")), ["DE-03"])
        self.assertEqual(only(self.q("nope", "x")), ["DE-03"])

    def test_malformed_reference_is_de02(self):
        for ref in ({"source": "doc", "version": "v2"}, {"source": "doc", "version": "v2", "quote": ""}, {"source": "doc", "version": "v2", "quote": 1},
                    {"version": "v2", "quote": "x"}, "doc", None):
            with self.subTest(repr(ref)):
                self.assertEqual(only(sources.check_quote(self.cat, self.roots, ref)), ["DE-02"])

    def test_extra_keys_of_a_source_ref_do_not_matter(self):
        ref = {"source": "doc", "version": "v2", "quote": "Common sentence.", "anchor": "x", "fragment": "y"}
        self.assertEqual(sources.check_quote(self.cat, self.roots, ref), [])

    def test_non_utf8_source_with_a_matching_hash_is_an_error(self):
        data = b"\xff\xfe broken"
        (self.ws / "v3.md").write_bytes(data)
        V(self.cat, "doc", "v3").update(sha256=sha(data), bytes=len(data))
        self.assertEqual(only(self.q("v3", "broken")), ["DE-13"])


class ReadLabelTests(Workspace):
    def test_verified_text_and_label_search(self):
        self.assertIn("Common sentence.", sources.verified_text(self.cat, self.roots, "doc", "v2"))
        occ = sources.find_label_in(self.cat, self.roots, "doc", "v2", "RT1")
        self.assertEqual([(o.line, o.column) for o in occ], [(2, 1)])
        self.assertEqual(sources.find_label_in(self.cat, self.roots, "doc", "v2", "RT2"), [])

    def test_errors_are_distinguishable(self):
        with self.assertRaises(sources.SourceLookupError):
            sources.verified_text(self.cat, self.roots, "doc", "nope")
        with self.assertRaises(sources.SourceLookupError):
            sources.verified_text(self.cat, self.roots, "nope", "v2")
        (self.ws / "v2.md").write_bytes(b"changed")
        with self.assertRaises(sources.SourceMismatch):
            sources.find_label_in(self.cat, self.roots, "doc", "v2", "RT1")
        (self.ws / "v2.md").unlink()
        with self.assertRaises(sources.SourceUnavailable):
            sources.find_label_in(self.cat, self.roots, "doc", "v2", "RT1")
        with self.assertRaises(sources.SourceUnavailable):
            sources.verified_text(self.cat, {}, "doc", "v2")

    def test_exception_classes_share_a_base(self):
        for c in (sources.SourceLookupError, sources.SourceUnavailable, sources.SourceMismatch):
            self.assertTrue(issubclass(c, sources.SourceError))


class TransitionTests(Workspace):
    def setUp(self):
        super().setUp()
        self.old = copy.deepcopy(self.cat)

    def t(self, new=None):
        return sources.check_transition(self.old, self.cat if new is None else new)

    def test_identical_catalogs(self):
        self.assertEqual(self.t(), [])

    def test_new_sources_and_versions_are_fine(self):
        S(self.cat, "doc")["versions"].append(ver("v4", "DRAFT", data=b"4\n", path="v4.md"))
        self.cat["sources"].append({"key": "other", "title": "o", "category": "DRAFT", "versions": [ver("v3", "DRAFT")]})
        self.assertEqual(self.t(), [])

    def test_removing_a_version_or_a_source_is_de06(self):
        S(self.cat, "doc")["versions"].pop()
        self.assertEqual(codes(self.t()), [("DE-06", "sources:doc/v3")])
        self.cat = good_catalog()
        self.cat["sources"].pop()
        self.assertEqual(codes(self.t()), [("DE-06", "sources:doc")])

    def test_a_version_never_changes_its_bytes_identity(self):
        V(self.cat, "doc", "v3")["sha256"] = sha(b"other")
        self.assertEqual(codes(self.t()), [("DE-06", "sources:doc/v3")])
        self.cat = good_catalog()
        V(self.cat, "doc", "v3")["bytes"] += 1
        self.assertEqual(codes(self.t()), [("DE-06", "sources:doc/v3")])

    def test_location_and_pinning_upgrade_may_change(self):
        v = V(self.cat, "doc", "v3")
        v["location"] = {"root": "ws", "path": "moved/v3.md"}
        v.update(pinning="git-blob", git_blob="a" * 40, commit="b" * 40)
        self.assertEqual(self.t(), [])

    def test_draft_to_ratified_without_a_source_is_an_error(self):
        V(self.cat, "doc", "v3")["status"] = "RATIFIED"
        self.assertEqual(codes(self.t()), [("DE-13", "sources:doc/v3")])

    def test_draft_to_ratified_with_a_ratification_record_passes_the_transition_rule(self):
        v = V(self.cat, "doc", "v3")
        v["status"], v["ratified_by"] = "RATIFIED", RB
        self.assertEqual(self.t(), [])

    def test_status_edges(self):
        allowed = [("DRAFT", "HISTORICAL"), ("RATIFIED", "HISTORICAL"), ("RATIFIED-MARKED", "HISTORICAL")]
        for a, b in allowed:
            old, new = copy.deepcopy(self.old), copy.deepcopy(self.cat)
            V(old, "doc", "v3")["status"] = a
            V(new, "doc", "v3")["status"] = b
            with self.subTest((a, b)):
                self.assertEqual(sources.check_transition(old, new), [])
        forbidden = [("HISTORICAL", "DRAFT"), ("HISTORICAL", "RATIFIED"), ("HISTORICAL", "RATIFIED-MARKED"), ("RATIFIED", "DRAFT"),
                     ("RATIFIED", "RATIFIED-MARKED"), ("RATIFIED-MARKED", "RATIFIED"), ("RATIFIED-MARKED", "DRAFT"), ("DRAFT", "RATIFIED-MARKED")]
        for a, b in forbidden:
            old, new = copy.deepcopy(self.old), copy.deepcopy(self.cat)
            for c, st in ((old, a), (new, b)):
                v = V(c, "doc", "v3")
                v["status"] = st
                if st.startswith("RATIFIED"):
                    v["ratified_by"] = RB
            with self.subTest((a, b)):
                got = codes(sources.check_transition(old, new))
                self.assertIn(("DE-13", "sources:doc/v3"), got)
                self.assertTrue(set(got) <= {("DE-13", "sources:doc/v3"), ("DE-06", "sources:doc/v3")}, got)    # DE-06 when ratified_by disappears

    def test_the_basis_of_a_ratification_cannot_be_rewritten(self):
        S(self.cat, "ratification")["versions"].append(ver("v3", "RATIFIED", path="v3.md"))
        V(self.cat, "doc", "v2")["ratified_by"] = {"source": "ratification", "version": "v3"}
        self.assertEqual(codes(self.t()), [("DE-06", "sources:doc/v2")])

    def test_malformed_input_does_not_crash_the_transition_check(self):
        for bad in (None, [], {"sources": "x"}, {"sources": [1, {"key": 3}, {"key": "a", "versions": "x"}]}):
            with self.subTest(repr(bad)):
                sources.check_transition(bad, self.cat)
                sources.check_transition(self.old, bad)

    def test_transition_does_not_modify_inputs(self):
        before = (copy.deepcopy(self.old), copy.deepcopy(self.cat))
        V(self.cat, "doc", "v3")["status"] = "RATIFIED"
        before = (copy.deepcopy(self.old), copy.deepcopy(self.cat))
        self.t()
        self.assertEqual((self.old, self.cat), before)


class CliTests(Workspace):
    def setUp(self):
        super().setUp()
        self.cp = Path(self._t.name) / "sources.json"
        canon.write_record(self.cp, self.cat)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sources.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_ok_with_advisories(self):
        code, out, _ = self.run_cli("check", "--catalog", str(self.cp), "--root", f"ws={self.ws}")
        self.assertEqual(code, 0, out)
        self.assertIn("AD-04", out)
        self.assertIn("sources: OK", out)

    def test_changed_byte_exits_1(self):
        (self.ws / "v2.md").write_bytes(b"changed")
        code, out, _ = self.run_cli("check", "--catalog", str(self.cp), "--root", f"ws={self.ws}")
        self.assertEqual(code, 1)
        self.assertIn("DE-13", out)

    def test_invalid_catalog_exits_1_and_missing_file_exits_3(self):
        bad = copy.deepcopy(self.cat)
        V(bad, "doc", "v3")["sha256"] = "x"
        p = Path(self._t.name) / "bad.json"
        canon.write_record(p, bad)
        self.assertEqual(self.run_cli("check", "--catalog", str(p))[0], 1)
        self.assertEqual(self.run_cli("check", "--catalog", str(self.cp.with_name("absent.json")))[0], 3)

    def test_old_catalog_comparison(self):
        new = copy.deepcopy(self.cat)
        V(new, "doc", "v3")["status"] = "RATIFIED"
        np = Path(self._t.name) / "new.json"
        canon.write_record(np, new)
        code, out, _ = self.run_cli("check", "--catalog", str(np), "--old-catalog", str(self.cp))
        self.assertEqual(code, 1)
        self.assertIn("DE-13", out)
        self.assertEqual(self.run_cli("check", "--catalog", str(self.cp), "--old-catalog", str(self.cp))[0], 0)

    def test_malformed_catalog_never_reaches_file_verification(self):
        bad = copy.deepcopy(self.cat)
        del V(bad, "doc", "v3")["location"]
        p = Path(self._t.name) / "bad.json"
        canon.write_record(p, bad)
        code, out, err = self.run_cli("check", "--catalog", str(p), "--root", f"ws={self.ws}")
        self.assertEqual((code, err), (1, ""))
        self.assertIn("missing field 'location'", out)

    def test_transition_findings_are_shown_even_when_the_new_catalog_is_invalid(self):
        new = copy.deepcopy(self.cat)
        S(new, "doc")["versions"].pop()                       # v3 removed: DE-06 (transition only)
        V(new, "doc", "v1")["sha256"] = "x"                    # and something malformed: DE-02 (validation)
        np = Path(self._t.name) / "new.json"
        canon.write_record(np, new)
        code, out, _ = self.run_cli("check", "--catalog", str(np), "--old-catalog", str(self.cp))
        self.assertEqual(code, 1)
        self.assertIn("DE-02", out)
        self.assertIn("DE-06", out)

    def test_transition_findings_are_shown_for_a_valid_catalog_too(self):
        new = copy.deepcopy(self.cat)
        S(new, "doc")["versions"].pop()
        np = Path(self._t.name) / "new.json"
        canon.write_record(np, new)
        code, out, _ = self.run_cli("check", "--catalog", str(np), "--old-catalog", str(self.cp))
        self.assertEqual(code, 1)
        self.assertIn("DE-06", out)

    def test_bad_root_argument_exits_3(self):
        self.assertEqual(self.run_cli("check", "--catalog", str(self.cp), "--root", "no-equals-sign")[0], 3)


# --- the real sources (machine-local; NOT RUN elsewhere) ------------------------------------------------------------------------
def _real_skip_reason():
    """None when the machine-local data is here; otherwise the concrete reason the real-source tests are NOT RUN."""
    m = LOCAL / "protected-manifest.json"
    if not m.is_file():
        return f"NOT RUN: {m} is not present (machine-local, not part of any patch)"
    if not (LOCAL / "sources.json").is_file():
        return f"NOT RUN: {LOCAL / 'sources.json'} is not present (build it with python -m clxreg.localcat build-sources)"
    ws = os.environ.get("CLX_WORKSPACE_ROOT") or json.loads(m.read_text(encoding="utf-8")).get("roots", {}).get("workspace", "")
    if not Path(ws).is_dir():
        return f"NOT RUN: the workspace root {ws!r} is not a directory on this machine (set CLX_WORKSPACE_ROOT to where the sources are, e.g. /mnt/c/... in WSL)"
    return None


def _real_roots():
    m = LOCAL / "protected-manifest.json"
    if _real_skip_reason():
        return None
    roots = dict(json.loads(m.read_text(encoding="utf-8")).get("roots", {}))
    if os.environ.get("CLX_WORKSPACE_ROOT"):
        roots["workspace"] = os.environ["CLX_WORKSPACE_ROOT"]
    return roots


@unittest.skipIf(_real_skip_reason(), _real_skip_reason() or "")
class RealSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roots = _real_roots()
        cls.cat, f = sources.load_catalog(LOCAL / "sources.json")
        assert f == [], [x.line() for x in f]

    def version(self, vid, key="micromap"):
        return next(v for s in self.cat["sources"] if s["key"] == key for v in s["versions"] if v["id"] == vid)

    def test_the_catalog_is_valid_and_the_files_match_their_pins(self):
        self.assertEqual(sources.validate_catalog(self.cat), [])
        f = sources.verify_files(self.cat, self.roots)
        self.assertFalse(blocking(f), [x.line() for x in f])

    def test_documented_hashes(self):
        self.assertTrue(self.version("ratified-bytes")["sha256"].startswith("8178ab3c"))
        self.assertTrue(self.version("marked-file")["sha256"].startswith("813558f7"))
        self.assertTrue(self.version("revision-1")["sha256"].startswith("4397961c"))

    def test_ratified_bytes_and_marked_file_are_two_versions_of_one_source(self):
        s = next(s for s in self.cat["sources"] if s["key"] == "micromap")
        self.assertEqual({v["id"] for v in s["versions"]} & {"ratified-bytes", "marked-file"}, {"ratified-bytes", "marked-file"})
        self.assertNotEqual(self.version("ratified-bytes")["sha256"], self.version("marked-file")["sha256"])
        self.assertEqual(self.version("ratified-bytes")["status"], "RATIFIED")
        self.assertEqual(self.version("marked-file")["status"], "RATIFIED-MARKED")
        self.assertEqual(self.version("revision-1")["status"], "HISTORICAL")

    def q(self, version, quote):
        return sources.check_quote(self.cat, self.roots, {"source": "micromap", "version": version, "quote": quote})

    def test_quote_in_both_ratified_versions(self):
        quote = "resolver test gaps (renamed from \"R1–R3\" of revision 1, proposal MO4)"
        self.assertEqual(self.q("ratified-bytes", quote), [])
        self.assertEqual(self.q("marked-file", quote), [])

    def test_quote_in_only_one_of_them(self):
        draft_status = "**Not ratified.** Not part of the ratified roadmap revision."
        marked_status = "**RATIFIED by the project owner on 2026-10-25 as the working MICROMAP, revision 2.**"
        self.assertEqual(self.q("ratified-bytes", draft_status), [])
        self.assertEqual(only(self.q("marked-file", draft_status)), ["DE-13"])
        self.assertEqual(self.q("marked-file", marked_status), [])
        self.assertEqual(only(self.q("ratified-bytes", marked_status)), ["DE-13"])

    def test_rt2_is_not_a_literal_occurrence_but_is_implied_by_the_range(self):
        for vid in ("ratified-bytes", "marked-file"):
            with self.subTest(vid):
                self.assertEqual(sources.find_label_in(self.cat, self.roots, "micromap", vid, "RT2"), [])
                self.assertGreaterEqual(len(sources.find_label_in(self.cat, self.roots, "micromap", vid, "RT1")), 1)
                self.assertGreaterEqual(len(sources.find_label_in(self.cat, self.roots, "micromap", vid, "RT3")), 1)
                self.assertEqual(self.q(vid, "RT1–RT3"), [])
        self.assertEqual(sources.find_label_in(self.cat, self.roots, "micromap", "revision-1", "RT1"), [])      # revision 1 knows only R1–R3


if __name__ == "__main__":
    unittest.main()
