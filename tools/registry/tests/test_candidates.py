"""IMP2-08 - dry-run generator of candidate aliases from a ledger and an approved mapping (tier A: it must never map what is ambiguous)."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from clxreg import aliases, candidates, canon, ledger, store
from tests.test_ledger import A_MD, B_MD, Fx, srcver
from tests.test_store import rec
from tests.test_units import cell, ods, p, row

RT1 = "micromap-resolver-gaps:RT1"


def mig(record="CLX-REQ-0001", status="ACTIVE", reason="pilot"):
    return {"disposition": "MIGRATED_AS_ALIAS", "record": record, "status": status, "reason": reason}


def mapping(**tokens):
    return {"schema": ledger.MAPPING_SCHEMA, "tokens": tokens}


def tree(root):
    return {str(x.relative_to(root)): x.read_bytes() for x in sorted(Path(root).rglob("*")) if x.is_file()}


class CFx(Fx):
    def setUp(self):
        super().setUp()
        self.reg = self.d / "reg"
        for t in store.STORED_TYPES:
            (self.reg / "records" / t).mkdir(parents=True)
        self.put_record(rec("REQ", 1))
        self.put_record(rec("REQ", 2))
        self.mapping = mapping(**{RT1: mig()})
        self.out = self.d / "out"

    def put_record(self, obj):
        canon.write_record(self.reg / "records" / obj["type"] / f"{obj['id']}.json", obj, overwrite=True)

    def gen(self, **kw):
        a = dict(run=self.run, src_cat=self.src, ns_obj=self.ns, amb_obj=self.amb, mapping=self.mapping, roots=self.roots, store_root=self.reg, out_dir=self.out)
        a.update(kw)
        return candidates.generate(**a)

    def read(self, rel):
        return json.loads((self.out / rel).read_text(encoding="utf-8"))


class HappyPathTests(CFx):
    def test_a_candidate_file_per_record_with_origin_status_and_a_literal_quote(self):
        self.gen()
        c = self.read("aliases/CLX-REQ-0001.json")
        self.assertEqual((c["schema"], c["record"]), (candidates.CANDIDATE_SCHEMA, "CLX-REQ-0001"))
        self.assertEqual(len(c["aliases"]), 1)
        a = c["aliases"][0]
        self.assertEqual((a["namespace"], a["value"], a["status"]), ("micromap-resolver-gaps", "RT1", "ACTIVE"))
        self.assertEqual(a["source"]["source"], "doc")
        self.assertEqual(a["source"]["version"], "v1")
        self.assertEqual(a["source"]["anchor"], "L2")
        self.assertEqual(a["source"]["quote"], A_MD.split("\n")[1])
        self.assertIn("5 occurrence", a["note"])

    def test_every_occurrence_is_listed_as_an_origin(self):
        self.gen()
        o = self.read("aliases/CLX-REQ-0001.json")["origins"]
        self.assertEqual(len(o), 1)
        occ = o[0]["occurrences"]
        self.assertEqual([(x["unit"], x["column"]) for x in occ], [("L2", 1), ("L2", 23), ("L7", 1), ("L7", 5), ("L7", 9)])
        self.assertTrue(all(x["text"] == "RT1" and x["source"] == "doc" and x["version"] == "v1" for x in occ))

    def test_the_candidates_pass_the_alias_checks_against_the_real_store(self):
        self.gen()
        recs = {r.id: copy.deepcopy(r.obj) for r in store.load(self.reg).records.values()}
        recs["CLX-REQ-0001"]["aliases"] = self.read("aliases/CLX-REQ-0001.json")["aliases"]
        f = aliases.check_aliases(recs, self.ns, self.src, self.roots)
        self.assertEqual([x for x in f if x.cls == "DATA_ERROR"], [])

    def test_the_manifest_counts_everything_the_import_found_not_only_what_was_mapped(self):
        self.gen()
        m = self.read("MANIFEST.json")
        after = self.read("ledger-after.json")
        self.assertEqual(m["schema"], candidates.MANIFEST_SCHEMA)
        self.assertEqual(m["dispositions"], after["summary"]["dispositions"])
        self.assertEqual(m["mapped"], [RT1])
        self.assertEqual(m["existing"], [])
        self.assertEqual(m["diff_check"], "exact")
        self.assertEqual(m["records"], [{"record": "CLX-REQ-0001", "file": "aliases/CLX-REQ-0001.json", "aliases": 1,
                                         "sha256": hashlib.sha256((self.out / "aliases/CLX-REQ-0001.json").read_bytes()).hexdigest()}])
        self.assertEqual(m["ledger_sha256"], hashlib.sha256((self.out / "ledger-after.json").read_bytes()).hexdigest())
        self.assertTrue(m["not_mapped"]["AMBIGUOUS"] > 0 and m["not_mapped"]["RANGE_NOT_EXPANDED"] > 0)
        self.assertNotIn("MIGRATED_AS_ALIAS", m["not_mapped"])
        self.assertEqual(sum(m["not_mapped"].values()) + 5, after["summary"]["entries"])        # 5 RT1 labels were mapped, everything else is counted

    def test_before_and_after_ledgers_are_written_and_differ_exactly_by_the_mapping(self):
        self.gen()
        d = ledger.diff_ledgers(self.read("ledger-before.json"), self.read("ledger-after.json"))
        self.assertEqual((d["added"], d["removed"], d["sources_changed"]), ([], [], []))
        self.assertEqual({(c["text"], c["unit"]) for c in d["changed"]}, {("RT1", "L2"), ("RT1", "L7")})
        self.assertEqual(len(d["changed"]), 5)

    def test_repeated_generation_is_byte_identical(self):
        self.gen()
        first = tree(self.out)
        self.out = self.d / "out2"
        self.gen()
        self.assertEqual(tree(self.out), first)

    def test_a_not_migrated_decision_is_counted_but_creates_no_candidate(self):
        self.mapping = mapping(**{"micromap-findings:F11": {"disposition": "NOT_MIGRATED", "reason": "owner: not a requirement"}})
        self.gen()
        self.assertFalse((self.out / "aliases").exists())
        m = self.read("MANIFEST.json")
        self.assertEqual((m["mapped"], m["declined"], m["records"]), ([], ["micromap-findings:F11"], []))

    def test_an_empty_mapping_still_documents_the_import(self):
        self.mapping = mapping()
        self.gen()
        self.assertEqual(self.read("MANIFEST.json")["records"], [])
        self.assertTrue((self.out / "ledger-after.json").is_file())

    def test_several_labels_for_one_record_in_one_file(self):
        self.mapping = mapping(**{RT1: mig(), "micromap-findings:F11": mig(status="HISTORICAL")})
        self.gen()
        c = self.read("aliases/CLX-REQ-0001.json")
        self.assertEqual([(a["namespace"], a["value"], a["status"]) for a in c["aliases"]],
                         [("micromap-findings", "F11", "HISTORICAL"), ("micromap-resolver-gaps", "RT1", "ACTIVE")])
        self.assertEqual(c["aliases"][0]["source"]["quote"], B_MD.split("\n")[0])         # CR kept: the quote is literal

    def test_labels_for_two_records_make_two_files(self):
        self.mapping = mapping(**{RT1: mig(), "micromap-findings:F11": mig("CLX-REQ-0002")})
        self.gen()
        self.assertEqual(sorted(n.replace("\\", "/") for n in tree(self.out)),
                         ["MANIFEST.json", "aliases/CLX-REQ-0001.json", "aliases/CLX-REQ-0002.json", "ledger-after.json", "ledger-before.json"])

    def test_output_files_are_canonical_json(self):
        self.gen()
        for name, data in tree(self.out).items():
            self.assertTrue(canon.is_canonical(data.decode("utf-8")), name)

    def test_nothing_outside_the_output_directory_changes(self):
        before = (tree(self.reg), {n: ((self.ws / n).read_bytes(), (self.ws / n).stat().st_mtime_ns) for n in self.files})
        self.gen()
        self.assertEqual((tree(self.reg), {n: ((self.ws / n).read_bytes(), (self.ws / n).stat().st_mtime_ns) for n in self.files}), before)

    def test_the_first_text_occurrence_is_the_evidence_when_a_label_also_occurs_in_an_ods(self):
        data = ods({"Plan": row(cell(p("RT1 is open")))})
        (self.ws / "r.ods").write_bytes(data)
        self.src["sources"][0]["versions"].append(srcver("v3", "r.ods", data))
        self.run["include"] = [{"source": "doc", "version": "v3"}, {"source": "doc", "version": "v1"}]
        self.gen()
        c = self.read("aliases/CLX-REQ-0001.json")
        self.assertEqual(c["aliases"][0]["source"]["version"], "v1")
        self.assertEqual(c["origins"][0]["occurrences"][0]["unit"], "Plan!R1C1/p1")        # the ODS occurrence is still listed first, as found


class RefusalTests(CFx):
    def refuses(self, **kw):
        with self.assertRaises(candidates.CandidateError) as cm:
            self.gen(**kw)
        self.assertFalse(self.out.exists(), "nothing may be written when the generation is refused")
        return str(cm.exception)

    def test_a_label_found_only_in_an_ods_is_refused_not_given_unchecked_evidence(self):
        data = ods({"Plan": row(cell(p("RT7 is open")))})
        (self.ws / "r.ods").write_bytes(data)
        self.src["sources"][0]["versions"].append(srcver("v3", "r.ods", data))
        self.run["include"] = [{"source": "doc", "version": "v3"}]
        self.assertIn("non-text (ODS)", self.refuses(mapping=mapping(**{"micromap-resolver-gaps:RT7": mig()})))

    def test_an_ambiguous_label_cannot_be_mapped_by_batch(self):
        msg = self.refuses(mapping=mapping(**{"plan-resolver-gaps-v1:R1": mig(status="HISTORICAL")}))
        self.assertIn("ambiguous", msg)

    def test_an_ambiguity_rule_blocks_mapping_too(self):
        amb = {"schema": "clx.ambiguity/1", "rules": [{"namespace": "micromap-findings", "value": "F11", "meanings": ["a", "b"], "basis": "x"}]}
        self.assertIn("ambiguous", self.refuses(amb_obj=amb, mapping=mapping(**{"micromap-findings:F11": mig()})))

    def test_a_label_inside_a_range_cannot_be_mapped(self):
        self.assertIn("no occurrence", self.refuses(mapping=mapping(**{"micromap-resolver-gaps:RT2": mig()})))

    def test_a_stale_mapping_entry_is_refused(self):
        self.assertIn("RT9", self.refuses(mapping=mapping(**{"micromap-resolver-gaps:RT9": mig()})))

    def test_a_mapping_to_a_record_that_does_not_exist_is_refused(self):
        self.assertIn("CLX-REQ-0099", self.refuses(mapping=mapping(**{RT1: mig("CLX-REQ-0099")})))

    def test_a_mapping_to_a_record_of_another_type_that_does_not_exist_is_refused(self):
        self.assertIn("CLX-SCN-0001", self.refuses(mapping=mapping(**{RT1: mig("CLX-SCN-0001")})))

    def test_an_invalid_store_is_refused(self):
        (self.reg / "records" / "REQ" / "CLX-REQ-0005.json").write_text("{nope", encoding="utf-8")
        self.assertIn("store", self.refuses())

    def test_an_incomplete_ledger_is_refused(self):
        (self.ws / "b.md").unlink()
        self.assertIn("complete", self.refuses())

    def test_a_changed_source_is_refused(self):
        (self.ws / "a.md").write_bytes(b"changed")
        self.assertIn("pinned", self.refuses())

    def test_the_alias_of_another_record_is_not_taken_over(self):
        self.put_record(rec("REQ", 2, aliases=[{"namespace": "micromap-resolver-gaps", "value": "RT1", "status": "ACTIVE",
                                                "source": {"source": "doc", "version": "v1", "anchor": "L2"}}]))
        self.assertIn("DE-05", self.refuses())

    def test_the_output_directory_must_be_new(self):
        self.out.mkdir()
        (self.out / "keep.txt").write_text("mine", encoding="utf-8")
        with self.assertRaises(candidates.CandidateError):
            self.gen()
        self.assertEqual((self.out / "keep.txt").read_text(encoding="utf-8"), "mine")
        self.assertEqual(sorted(x.name for x in self.out.iterdir()), ["keep.txt"])

    def test_the_output_directory_is_never_the_registry_or_a_source_root(self):
        for bad in (self.reg / "records" / "out", self.reg / "out", self.ws / "out"):
            with self.subTest(str(bad)):
                with self.assertRaises(candidates.CandidateError):
                    self.gen(out_dir=bad)
                self.assertFalse(bad.exists())

    def test_a_mapping_whose_difference_is_not_exact_is_refused_before_anything_is_written(self):
        from unittest import mock
        from clxreg.findings import data_error
        with mock.patch.object(candidates, "check_mapping_diff", return_value=[data_error("DE-13", "ledger", "boom")]):
            self.assertIn("boom", self.refuses())

    def test_the_parent_of_the_output_directory_must_exist(self):
        with self.assertRaises(candidates.CandidateError):
            self.gen(out_dir=self.d / "missing" / "out")

    def test_invalid_inputs_are_refused(self):
        with self.assertRaises(candidates.CandidateError):
            self.gen(mapping=None)
        with self.assertRaises(candidates.CandidateError):
            self.gen(run=dict(self.run, include=[]))
        self.assertFalse(self.out.exists())

    def test_a_missing_store_is_refused(self):
        self.assertIn("store", self.refuses(store_root=self.d / "nope"))


class ExistingAliasTests(CFx):
    def existing(self, status="ACTIVE"):
        return {"namespace": "micromap-resolver-gaps", "value": "RT1", "status": status,
                "source": {"source": "doc", "version": "v1", "anchor": "L2", "quote": A_MD.split("\n")[1]}}

    def test_an_alias_the_record_already_has_is_not_proposed_again(self):
        self.put_record(rec("REQ", 1, aliases=[self.existing()]))
        self.gen()
        self.assertFalse((self.out / "aliases").exists())
        m = self.read("MANIFEST.json")
        self.assertEqual((m["mapped"], m["existing"], m["records"]), ([RT1], [RT1], []))

    def test_an_existing_alias_with_another_status_is_a_conflict_not_a_silent_skip(self):
        self.put_record(rec("REQ", 1, aliases=[self.existing("HISTORICAL")]))
        with self.assertRaises(candidates.CandidateError) as cm:
            self.gen()
        self.assertIn("status", str(cm.exception))
        self.assertFalse(self.out.exists())


class MappingDiffTests(unittest.TestCase):
    def entry(self, text="RT1", disp="NOT_MIGRATED", ns="micromap-resolver-gaps", **kw):
        e = {"source": "s", "version": "v", "unit": "L1", "column": 1, "length": len(text), "class": "LABEL", "text": text, "namespace": ns, "disposition": disp}
        e.update(kw)
        return e

    def diff(self, changed=(), added=(), removed=(), sources=()):
        return {"added": list(added), "removed": list(removed), "sources_changed": list(sources),
                "changed": [dict({k: self.entry()[k] for k in ("source", "version", "unit", "column", "length", "class", "text")}, **c) for c in changed]}

    def test_exact_difference_is_accepted(self):
        m = mapping(**{RT1: mig()})
        d = self.diff(changed=[{"before": {"disposition": "NOT_MIGRATED"}, "after": {"disposition": "MIGRATED_AS_ALIAS"}}])
        self.assertEqual(candidates.check_mapping_diff(d, m, [self.entry(disposition="MIGRATED_AS_ALIAS", record="CLX-REQ-0001", status="ACTIVE")]), [])

    def test_anything_beyond_the_mapping_is_a_finding(self):
        m = mapping(**{RT1: mig()})
        after = [self.entry(disposition="MIGRATED_AS_ALIAS")]
        ch = {"before": {"disposition": "NOT_MIGRATED"}, "after": {"disposition": "MIGRATED_AS_ALIAS"}}
        for name, d in {"added entry": self.diff(changed=[ch], added=[self.entry("RT3")]), "removed entry": self.diff(changed=[ch], removed=[self.entry("RT3")]),
                        "source changed": self.diff(changed=[ch], sources=[["s", "v"]]),
                        "an unmapped entry changed": self.diff(changed=[ch, dict(ch, text="RT3")]), "no change at all": self.diff()}.items():
            with self.subTest(name):
                self.assertTrue(candidates.check_mapping_diff(d, m, after), name)

    def test_an_entry_the_mapping_does_not_name_must_not_change(self):
        m = mapping(**{RT1: mig()})
        after = [self.entry(disposition="MIGRATED_AS_ALIAS"), self.entry("RT3", disposition="MIGRATED_AS_ALIAS")]
        ch = {"before": {"disposition": "NOT_MIGRATED"}, "after": {"disposition": "MIGRATED_AS_ALIAS"}}
        d = self.diff(changed=[ch, dict(ch, text="RT3", length=3)])
        f = candidates.check_mapping_diff(d, m, after)
        self.assertEqual([x.record for x in f], ["mapping:micromap-resolver-gaps:RT3"])
        self.assertIn("does not name it", f[0].message)

    def test_fields_beyond_the_decision_must_not_change(self):
        m = mapping(**{RT1: mig()})
        after = [self.entry(disposition="MIGRATED_AS_ALIAS")]
        d = self.diff(changed=[{"before": {"disposition": "NOT_MIGRATED", "contained": []}, "after": {"disposition": "MIGRATED_AS_ALIAS", "contained": [1]}}])
        self.assertTrue(any("fields other than" in x.message for x in candidates.check_mapping_diff(d, m, after)))

    def test_a_changed_entry_that_is_not_a_label_is_a_finding(self):
        m = mapping(**{RT1: mig()})
        ch = {"before": {"disposition": "NOT_MIGRATED"}, "after": {"disposition": "MIGRATED_AS_ALIAS"}}
        for e in (self.entry(**{"class": "UNCLASSIFIED"}), {k: v for k, v in self.entry().items() if k != "namespace"}):
            with self.subTest(e.get("class")):
                f = candidates.check_mapping_diff(self.diff(changed=[ch]), m, [e])
                self.assertTrue(any("not a mappable label" in x.message for x in f))

    def test_a_mapping_key_that_changed_nothing_is_a_finding(self):
        m = mapping(**{RT1: mig(), "micromap-findings:F11": mig()})
        ch = {"before": {"disposition": "NOT_MIGRATED"}, "after": {"disposition": "MIGRATED_AS_ALIAS"}}
        f = candidates.check_mapping_diff(self.diff(changed=[ch]), m, [self.entry(disposition="MIGRATED_AS_ALIAS")])
        self.assertTrue(any("F11" in x.message for x in f))


class CliTests(CFx):
    def write(self, name, obj):
        p_ = self.d / name
        canon.write_record(p_, obj, overwrite=True)
        return str(p_)

    def args(self, out=None):
        return ["generate", "--run", self.write("run.json", self.run), "--catalog", self.write("src.json", self.src), "--namespaces", self.write("ns.json", self.ns),
                "--mapping", self.write("map.json", self.mapping), "--store-root", str(self.reg), "--root", f"ws={self.ws}", "--out", str(out or self.out)]

    def cli(self, *argv):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = candidates.main(list(argv))
        return code, o.getvalue(), e.getvalue()

    def test_generate_and_refuse_to_run_twice_into_the_same_directory(self):
        code, out, _ = self.cli(*self.args())
        self.assertEqual(code, 0, out)
        self.assertIn("candidate files: 1", out)
        code, _, err = self.cli(*self.args())
        self.assertEqual(code, 3)
        self.assertIn("exist", err)

    def test_refusals_exit_3(self):
        self.mapping = mapping(**{"plan-resolver-gaps-v1:R1": mig()})
        code, _, err = self.cli(*self.args())
        self.assertEqual(code, 3)
        self.assertIn("ambiguous", err)

    def test_the_ambiguity_file_is_used(self):
        amb = self.write("amb.json", {"schema": "clx.ambiguity/1", "rules": [{"namespace": "micromap-resolver-gaps", "meanings": ["a", "b"], "basis": "x"}]})
        code, _, err = self.cli(*self.args(), "--ambiguity", amb)
        self.assertEqual(code, 3)
        self.assertIn("ambiguous", err)


if __name__ == "__main__":
    unittest.main()
