"""S0 open point - machine-local catalogs: a documented, reproducible build in which every historical claim carries a literal basis (tier B)."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from clxreg import canon, localcat, namespaces, sources


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Fx(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.ws = self.d / "ws"
        self.ws.mkdir()
        self.doc = b"# Document\nRT1 is a label.\nStatus line.\n"
        self.rev1 = b"# Document, first draft\nR1 is a label.\n"
        self.rec_template = "Record of the decision.\nThe owner ratified the document, SHA-256 `{h}`.\nOnly the status block was changed.\n"
        self.rec = self.rec_template.format(h=sha(self.doc)).encode()
        self.log = f"| 1 | first draft; SHA-256 `{sha(self.rev1)}` |\n".encode()
        (self.ws / "doc.md").write_bytes(self.doc + self.log)       # the document's revision log names the hash of revision 1
        self.docfull = self.doc + self.log
        self.rec = self.rec_template.format(h=sha(self.docfull)).encode()
        (self.ws / "rec.md").write_bytes(self.rec)
        (self.ws / "rev1.md").write_bytes(self.rev1)
        self.roots = {"ws": str(self.ws)}
        self.manifest = {"roots": {"ws": str(self.ws)}, "entries": [{"root": "ws", "path": "rec.md", "sha256": sha(self.rec), "source": "inventory"}]}

    def spec(self):
        return {"schema": localcat.SPEC_SCHEMA, "sources": [
            {"key": "rec", "title": "Ratification record", "category": "RATIFIED", "subtype": "RATIFICATION-RECORD", "versions": [
                {"id": "r1", "location": {"root": "ws", "path": "rec.md"}, "sha256": sha(self.rec), "status": "RATIFIED",
                 "basis": {"sha256": {"protected_manifest": True},
                           "status": {"quote_in": {"source": "rec", "version": "r1"}, "quote": "The owner ratified the document"}}}]},
            {"key": "doc", "title": "The document", "category": "RATIFIED", "versions": [
                {"id": "first", "location": {"root": "ws", "path": "rev1.md"}, "sha256": sha(self.rev1), "status": "HISTORICAL",
                 "basis": {"sha256": {"quote_in": {"source": "doc", "version": "ratified"}, "quote": f"| 1 | first draft; SHA-256 `{sha(self.rev1)}` |"},
                           "status": {"quote_in": {"source": "doc", "version": "ratified"}, "quote": "| 1 | first draft;"}}},
                {"id": "ratified", "location": {"root": "ws", "path": "doc.md"}, "sha256": sha(self.docfull), "status": "RATIFIED",
                 "ratified_by": {"source": "rec", "version": "r1"},
                 "basis": {"sha256": {"quote_in": {"source": "rec", "version": "r1"}, "quote": f"SHA-256 `{sha(self.docfull)}`"},
                           "status": {"quote_in": {"source": "rec", "version": "r1"}, "quote": "The owner ratified the document"}}}]},
        ]}

    def build(self, spec=None, manifest="default"):
        return localcat.build_sources(spec or self.spec(), self.roots, self.manifest if manifest == "default" else manifest)


class BuildTests(Fx):
    def test_the_catalog_is_built_valid_and_verified_against_the_files(self):
        cat = self.build()
        self.assertEqual(sources.validate_catalog(cat), [])
        self.assertFalse([f for f in sources.verify_files(cat, self.roots) if f.cls == "DATA_ERROR"])
        v = {x["id"]: x for s in cat["sources"] for x in s["versions"]}
        self.assertEqual((v["first"]["status"], v["ratified"]["status"], v["r1"]["status"]), ("HISTORICAL", "RATIFIED", "RATIFIED"))
        self.assertEqual(v["ratified"]["ratified_by"], {"source": "rec", "version": "r1"})
        self.assertEqual(v["ratified"]["bytes"], len(self.docfull))
        self.assertEqual(v["ratified"]["pinning"], "sha256-only")

    def test_each_version_says_what_its_claims_rest_on(self):
        v = {x["id"]: x for s in self.build()["sources"] for x in s["versions"]}
        self.assertIn("protected manifest", v["r1"]["note"])
        self.assertIn("rec/r1", v["ratified"]["note"])
        self.assertIn("doc/ratified", v["first"]["note"])

    def test_the_build_is_deterministic_and_canonical(self):
        a, b = canon.dumps(self.build()), canon.dumps(self.build())
        self.assertEqual(a, b)

    def test_the_spec_is_not_modified(self):
        s = self.spec()
        before = copy.deepcopy(s)
        self.build(s)
        self.assertEqual(s, before)


class RefusalTests(Fx):
    def refuses(self, spec=None, manifest="default", text=None):
        with self.assertRaises(localcat.SpecError) as cm:
            self.build(spec, manifest)
        if text:
            self.assertIn(text, str(cm.exception))

    def ver(self, spec, sk, vid):
        return next(v for s in spec["sources"] if s["key"] == sk for v in s["versions"] if v["id"] == vid)

    def test_a_declared_hash_that_differs_from_the_file(self):
        s = self.spec()
        self.ver(s, "doc", "first")["sha256"] = "0" * 64
        self.refuses(s, text="doc/first")

    def test_a_missing_file(self):
        (self.ws / "rev1.md").unlink()
        self.refuses(text="does not exist")

    def test_a_location_outside_the_root(self):
        (self.d / "outside.md").write_bytes(self.rev1)                 # the file exists, only its place is wrong
        s = self.spec()
        self.ver(s, "doc", "first")["location"]["path"] = "../outside.md"
        self.refuses(s, text="leaves its root")

    def test_a_basis_quote_that_is_not_in_the_cited_file(self):
        s = self.spec()
        self.ver(s, "doc", "first")["basis"]["status"]["quote"] = "| 1 | first draft!"
        self.refuses(s, text="not a literal")

    def test_a_hash_basis_quote_that_does_not_contain_the_hash(self):
        s = self.spec()
        self.ver(s, "doc", "first")["basis"]["sha256"]["quote"] = "| 1 | first draft;"
        self.refuses(s, text="does not contain the hash")

    def test_a_version_cannot_document_its_own_hash(self):
        s = self.spec()
        self.ver(s, "doc", "first")["basis"]["sha256"]["quote_in"] = {"source": "doc", "version": "first"}
        self.refuses(s, text="itself")

    def test_a_basis_pointing_at_a_version_that_is_not_in_the_spec(self):
        s = self.spec()
        self.ver(s, "doc", "first")["basis"]["status"]["quote_in"] = {"source": "doc", "version": "nope"}
        self.refuses(s, text="nope")

    def test_the_protected_manifest_basis_needs_a_matching_entry(self):
        self.refuses(manifest=None, text="manifest")
        bad = copy.deepcopy(self.manifest)
        bad["entries"][0]["sha256"] = "1" * 64
        self.refuses(manifest=bad, text="manifest")
        self.refuses(manifest={"roots": {}, "entries": []}, text="manifest")

    def test_every_version_needs_both_bases(self):
        for which in ("sha256", "status"):
            s = self.spec()
            del self.ver(s, "doc", "first")["basis"][which]
            with self.subTest(which):
                self.refuses(s, text=which)
        s = self.spec()
        del self.ver(s, "doc", "first")["basis"]
        self.refuses(s)

    def test_shape_errors(self):
        for name, mutate in {
            "wrong schema": lambda s: s.update(schema="x"), "unknown field": lambda s: s.update(x=1), "sources not a list": lambda s: s.update(sources={}),
            "version unknown field": lambda s: self.ver(s, "doc", "first").update(x=1), "basis unknown field": lambda s: self.ver(s, "doc", "first")["basis"].update(x=1),
            "quote empty": lambda s: self.ver(s, "doc", "first")["basis"]["status"].update(quote=""),
            "basis with both kinds": lambda s: self.ver(s, "rec", "r1")["basis"]["sha256"].update(quote_in={"source": "doc", "version": "ratified"}, quote="x"),
            "status missing": lambda s: self.ver(s, "doc", "first").pop("status"), "sha missing": lambda s: self.ver(s, "doc", "first").pop("sha256"),
        }.items():
            s = self.spec()
            mutate(s)
            with self.subTest(name):
                self.refuses(s)

    def test_the_protected_manifest_can_only_document_a_hash_not_a_status(self):
        s = self.spec()
        self.ver(s, "doc", "first")["basis"]["status"] = {"protected_manifest": True}
        self.refuses(s, text="status")

    def test_a_version_listed_twice(self):
        s = self.spec()
        s["sources"][1]["versions"].append(copy.deepcopy(s["sources"][1]["versions"][0]))
        self.refuses(s, text="listed twice")

    def test_a_ratified_version_without_its_ratification_is_refused_by_the_catalog_rules(self):
        s = self.spec()
        del self.ver(s, "doc", "ratified")["ratified_by"]
        self.refuses(s, text="ratified_by")

    def test_inputs_that_are_not_what_they_say_are_refused(self):
        with self.assertRaises(localcat.SpecError):
            localcat.build_sources(None, self.roots, self.manifest)
        with self.assertRaises(localcat.SpecError):
            localcat.build_sources(self.spec(), {}, self.manifest)


class CheckNamespacesTests(Fx):
    def ns(self, quote="RT1 is a label."):
        return {"schema": namespaces.SCHEMA, "namespaces": [
            {"key": "rt", "label_pattern": "RT[0-9]+", "meaning": "resolver gaps", "authority": {"source": "doc", "version": "ratified", "quote": quote}, "status": "LIVE",
             "maps_to": "REQ", "distinct_from": []}]}

    def test_quotes_are_checked_and_required(self):
        cat = self.build()
        self.assertEqual(namespaces.check_authorities(self.ns(), cat, self.roots, require_quote=True), [])
        f = namespaces.check_authorities(self.ns("RT1 is NOT a label."), cat, self.roots, require_quote=True)
        self.assertEqual([x.code for x in f], ["DE-13"])
        n = self.ns()
        del n["namespaces"][0]["authority"]["quote"]
        f = namespaces.check_authorities(n, cat, self.roots, require_quote=True)
        self.assertEqual([x.code for x in f], ["DE-13"])
        self.assertIn("quote", f[0].message)
        self.assertEqual(namespaces.check_authorities(n, cat, self.roots), [])


class CliTests(Fx):
    def cli(self, *argv):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = localcat.main(list(argv))
        return code, o.getvalue(), e.getvalue()

    def files(self):
        sp, mp = self.d / "spec.json", self.d / "manifest.json"
        canon.write_record(sp, self.spec(), overwrite=True)
        mp.write_text(json.dumps(self.manifest), encoding="utf-8")
        np = self.d / "ns.json"
        canon.write_record(np, CheckNamespacesTests.ns(self), overwrite=True)
        return sp, mp, np

    def test_build_check_and_reproduce(self):
        sp, mp, np = self.files()
        out = self.d / "sources.json"
        code, o, _ = self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(out))
        self.assertEqual(code, 0, o)
        self.assertTrue(canon.is_canonical(out.read_text(encoding="utf-8")))
        self.assertEqual(self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(out))[0], 3)
        code, o, _ = self.cli("check", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--catalog", str(out), "--namespaces", str(np))
        self.assertEqual(code, 0, o)
        self.assertIn("reproduced", o)

    def test_check_finds_a_catalog_that_is_not_what_the_spec_gives(self):
        sp, mp, np = self.files()
        out = self.d / "sources.json"
        self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(out))
        cat = json.loads(out.read_text(encoding="utf-8"))
        cat["sources"][1]["versions"][0]["status"] = "DRAFT"
        canon.write_record(out, cat, overwrite=True)
        code, o, _ = self.cli("check", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--catalog", str(out), "--namespaces", str(np))
        self.assertEqual(code, 1)
        self.assertIn("differs from what the spec gives", o)

    def test_check_finds_a_namespace_quote_that_is_not_in_the_source(self):
        sp, mp, np = self.files()
        out = self.d / "sources.json"
        self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(out))
        canon.write_record(np, CheckNamespacesTests.ns(self, "invented"), overwrite=True)
        code, o, _ = self.cli("check", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--catalog", str(out), "--namespaces", str(np))
        self.assertEqual(code, 1)
        self.assertIn("DE-13", o)

    def test_check_requires_a_quote_for_every_namespace_authority(self):
        sp, mp, np = self.files()
        out = self.d / "sources.json"
        self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(out))
        n = CheckNamespacesTests.ns(self)
        del n["namespaces"][0]["authority"]["quote"]
        canon.write_record(np, n, overwrite=True)
        code, o, _ = self.cli("check", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--catalog", str(out), "--namespaces", str(np))
        self.assertEqual(code, 1)
        self.assertIn("no quote", o)

    def test_check_finds_a_source_file_that_changed_after_the_catalog_was_built(self):
        sp, mp, np = self.files()
        out = self.d / "sources.json"
        self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(out))
        (self.ws / "rev1.md").write_bytes(b"changed")
        code, _, err = self.cli("check", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--catalog", str(out), "--namespaces", str(np))
        self.assertEqual(code, 3)
        self.assertIn("doc/first", err)

    def test_a_malformed_catalog_is_reported_without_a_crash(self):
        sp, mp, np = self.files()
        out = self.d / "sources.json"
        self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(out))
        cat = json.loads(out.read_text(encoding="utf-8"))
        del cat["sources"][1]["versions"][0]["location"]
        canon.write_record(out, cat, overwrite=True)
        code, o, err = self.cli("check", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--catalog", str(out), "--namespaces", str(np))
        self.assertEqual((code, err), (1, ""))
        self.assertIn("missing field 'location'", o)

    def test_a_spec_that_is_not_canonical_json_is_refused(self):
        sp, mp, _ = self.files()
        sp.write_text(json.dumps(self.spec(), indent=4), encoding="utf-8")
        code, _, err = self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(self.d / "y.json"))
        self.assertEqual(code, 3)
        self.assertIn("canonical", err)

    def test_a_refused_spec_exits_3(self):
        sp, mp, _ = self.files()
        (self.ws / "rev1.md").write_bytes(b"changed")
        code, _, err = self.cli("build-sources", "--spec", str(sp), "--manifest", str(mp), "--root", f"ws={self.ws}", "--out", str(self.d / "x.json"))
        self.assertEqual(code, 3)
        self.assertIn("doc/first", err)


if __name__ == "__main__":
    unittest.main()
