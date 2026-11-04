"""IMP2-05 - the import ledger: every occurrence kept, located, literal, dispositioned; nothing dropped, merged, expanded or invented (tier A)."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from clxreg import canon, ledger, namespaces, sources, units
from tests.test_patterns import catalog as ns_catalog
from tests.test_units import cell, ods, p, row

A_MD = ("# Heading\n"
        "RT1–RT3 are the gaps; RT1 is open. R1 and R2 here.\n"
        "step P1.2-M3d and M3d; gate E1-1 and E1 and Q99.\n"
        "DONE: PR #17, 0ca9b73 — 330 of 330 PASS (CI run 40066814847)\n"
        "\n"
        "plain words only\n"
        "RT1 RT1 RT1\n")
B_MD = "R1 once more, and F11.\r\nQ99-Q100  \tRT3\r\n"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def srcver(vid, name, data, status="DRAFT"):
    return {"id": vid, "sha256": sha(data), "bytes": len(data), "pinning": "sha256-only", "status": status, "location": {"root": "ws", "path": name}}


class Fx(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.ws = self.d / "ws"
        self.ws.mkdir()
        self.files = {"a.md": A_MD.encode("utf-8"), "b.md": B_MD.encode("utf-8")}
        for n, b in self.files.items():
            (self.ws / n).write_bytes(b)
        self.roots = {"ws": str(self.ws)}
        self.src = {"schema": sources.SCHEMA, "sources": [
            {"key": "doc", "title": "Doc", "category": "DRAFT", "versions": [srcver("v1", "a.md", self.files["a.md"]), srcver("v2", "b.md", self.files["b.md"])]}]}
        self.ns = ns_catalog()
        self.run = {"schema": ledger.RUN_SCHEMA, "include": [{"source": "doc", "version": "v1"}, {"source": "doc", "version": "v2"}], "excluded": []}
        self.amb = None
        self.mapping = None

    def build(self, **kw):
        a = dict(run=self.run, src_cat=self.src, ns_obj=self.ns, amb_obj=self.amb, mapping=self.mapping, roots=self.roots)
        a.update(kw)
        return ledger.build_ledger(**a)

    def entries(self, led, **kw):
        out = led["entries"]
        for k, v in kw.items():
            out = [e for e in out if e.get(k) == v]
        return out


def at(led, source_ver, unit, text, cls=None):
    return [e for e in led["entries"] if e.get("version") == source_ver and e.get("unit") == unit and e.get("text") == text and (cls is None or e["class"] == cls)]


class BasicShapeTests(Fx):
    def test_every_entry_has_identity_location_literal_text_class_and_a_closed_disposition(self):
        led = self.build()
        self.assertEqual(led["schema"], ledger.SCHEMA)
        for e in led["entries"]:
            self.assertIn(e["disposition"], ledger.DISPOSITIONS)
            self.assertIn(e["class"], ledger.CLASSES)
            self.assertEqual(sha(self.files[{"v1": "a.md", "v2": "b.md"}[e["version"]]]), e["sha256"])
            self.assertTrue(e["text"] and e["unit"] and e["column"] >= 1 and e["length"] == len(e["text"]) and e["line"] >= 1)
        self.assertEqual([e["n"] for e in led["entries"]], list(range(1, len(led["entries"]) + 1)))
        self.assertEqual(ledger.validate_ledger(led), [])

    def test_entries_are_literally_the_source_text_at_their_location(self):
        led = self.build()
        lines = {"v1": A_MD.split("\n"), "v2": B_MD.split("\n")}
        for e in led["entries"]:
            line = lines[e["version"]][e["line"] - 1]
            self.assertEqual(line[e["column"] - 1:e["column"] - 1 + e["length"]], e["text"])

    def test_every_occurrence_on_one_line_is_kept(self):
        led = self.build()
        self.assertEqual([(e["column"]) for e in self.entries(led, version="v1", unit="L7", text="RT1")], [1, 5, 9])

    def test_the_range_is_one_range_entry_its_members_are_not_invented_and_its_ends_are_kept(self):
        led = self.build()
        self.assertEqual([e["disposition"] for e in at(led, "v1", "L2", "RT1–RT3")], ["RANGE_NOT_EXPANDED"])
        self.assertEqual(at(led, "v1", "L2", "RT1–RT3")[0]["ends"], ["RT1", "RT3"])
        self.assertEqual([e for e in led["entries"] if e["text"] == "RT2"], [])
        self.assertEqual(len(at(led, "v1", "L2", "RT3", "LABEL")), 1)

    def test_the_same_label_in_two_namespaces_is_ambiguous_with_both_candidates_and_has_no_identity(self):
        led = self.build()
        e = at(led, "v1", "L2", "R1")[0]
        self.assertEqual((e["disposition"], e["candidates"]), ("AMBIGUOUS", ["plan-resolver-gaps-v1", "risk-classes"]))
        self.assertNotIn("record", e)
        self.assertNotIn("namespace", e)
        r2 = at(led, "v1", "L2", "R2")[0]
        self.assertEqual((r2["disposition"], r2["candidates"]), ("AMBIGUOUS", ["plan-resolver-gaps-v1", "risk-classes"]))

    def test_an_unambiguous_label_keeps_its_historical_namespace_and_is_not_migrated_by_default(self):
        led = self.build()
        e = at(led, "v1", "L2", "RT3", "LABEL")[0]
        self.assertEqual((e["namespace"], e["disposition"]), ("micromap-resolver-gaps", "NOT_MIGRATED"))
        self.assertIn("no mapping", e["reason"])
        f = at(led, "v2", "L1", "F11")[0]
        self.assertEqual(f["namespace"], "micromap-findings")

    def test_label_like_tokens_of_no_namespace_are_unclassified_not_dropped(self):
        led = self.build()
        self.assertEqual(at(led, "v1", "L3", "Q99")[0]["disposition"], "UNCLASSIFIED_LABEL")
        self.assertEqual([e["text"] for e in self.entries(led, version="v2", unit="L2", **{"class": "UNCLASSIFIED"})], ["Q99", "Q100"])

    def test_a_shorter_label_inside_a_longer_one_is_kept_inside_it(self):
        led = self.build()
        outer = at(led, "v1", "L3", "P1.2-M3d")[0]
        self.assertIn({"text": "M3d", "column": 11, "class": "LABEL", "namespaces": ["bare-step-label"]}, outer["contained"])
        self.assertEqual([e["column"] for e in at(led, "v1", "L3", "M3d")], [19])

    def test_original_states_references_and_result_phrases_are_recorded_without_interpretation(self):
        led = self.build()
        for text, cls in (("DONE", "STATE_WORD"), ("PR #17", "REFERENCE"), ("0ca9b73", "REFERENCE"), ("330 of 330", "RESULT_PHRASE"), ("PASS", "RESULT_PHRASE"),
                          ("CI run 40066814847", "REFERENCE")):
            es = at(led, "v1", "L4", text, cls)
            with self.subTest(text):
                self.assertEqual(len(es), 1)
                self.assertEqual(es[0]["disposition"], "UNCLASSIFIED_LABEL")
                self.assertIn("patterns", es[0])
                self.assertNotIn("record", es[0])

    def test_crlf_and_non_breaking_space_do_not_disturb_columns_or_text(self):
        led = self.build()
        e = at(led, "v2", "L2", "RT3")[0]
        self.assertEqual(e["column"], 12)                            # "Q99-Q100" (8) + space + NBSP + TAB, then RT3
        self.assertTrue(all("\r" not in x["text"] for x in led["entries"]))

    def test_ledger_is_canonical_json_and_deterministic(self):
        a, b = canon.dumps(self.build()), canon.dumps(self.build())
        self.assertEqual(a, b)
        self.assertTrue(canon.is_canonical(a))

    def test_inputs_are_not_modified(self):
        before = [copy.deepcopy(x) for x in (self.run, self.src, self.ns)]
        self.build()
        self.assertEqual([self.run, self.src, self.ns], before)


class CoverageTests(Fx):
    def test_the_coverage_map_says_which_lines_carry_nothing(self):
        led = self.build()
        s = led["sources"][0]
        self.assertEqual((s["source"], s["version"], s["status"]), ("doc", "v1", "PROCESSED"))
        self.assertEqual(s["units"], 8)
        self.assertEqual(s["blank_units"], 2)                        # the empty line and the final empty unit
        self.assertEqual(s["uncovered_line_ranges"], [[1, 1], [6, 6]])      # "# Heading" and "plain words only"
        self.assertEqual(s["uncovered_count"], 2)
        self.assertEqual(s["units_with_entries"], 4)
        self.assertEqual(s["uncovered_sha256"], hashlib.sha256("L1\nL6".encode()).hexdigest())

    def test_adjacent_uncovered_lines_form_one_range(self):
        text = b"plain\nwords\nRT1\nmore\nstill\nmore\nRT1\n"
        (self.ws / "c.md").write_bytes(text)
        self.src["sources"][0]["versions"].append(srcver("v3", "c.md", text))
        self.run["include"] = [{"source": "doc", "version": "v3"}]
        s = self.build()["sources"][0]
        self.assertEqual(s["uncovered_line_ranges"], [[1, 2], [4, 6]])
        self.assertEqual(s["uncovered_count"], 5)

    def test_sources_are_listed_in_run_order_with_their_pinned_hash(self):
        led = self.build()
        self.assertEqual([(s["source"], s["version"], s["sha256"]) for s in led["sources"]],
                         [("doc", "v1", sha(self.files["a.md"])), ("doc", "v2", sha(self.files["b.md"]))])

    def test_counts_in_the_summary_match_the_entries(self):
        led = self.build()
        by = {}
        for e in led["entries"]:
            by[e["disposition"]] = by.get(e["disposition"], 0) + 1
        self.assertEqual(led["summary"]["dispositions"], by)
        self.assertEqual(led["summary"]["entries"], len(led["entries"]))
        self.assertEqual(sum(led["summary"]["classes"].values()), len(led["entries"]))
        self.assertTrue(led["complete"])
        self.assertEqual(led["problems"], [])


class MappingTests(Fx):
    def mp(self, **tokens):
        return {"schema": ledger.MAPPING_SCHEMA, "tokens": tokens}

    def test_a_mapped_label_carries_record_status_and_reason_unmapped_ones_stay_not_migrated(self):
        self.mapping = self.mp(**{"micromap-resolver-gaps:RT1": {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0001", "status": "ACTIVE", "reason": "pilot"}})
        led = self.build()
        e = at(led, "v1", "L2", "RT1", "LABEL")[0]
        self.assertEqual((e["disposition"], e["record"], e["status"], e["reason"]), ("MIGRATED_AS_ALIAS", "CLX-REQ-0001", "ACTIVE", "pilot"))
        self.assertEqual((led["problems"], led["complete"]), ([], True))
        self.assertEqual(at(led, "v1", "L2", "RT3", "LABEL")[0]["disposition"], "NOT_MIGRATED")
        self.assertTrue(all(x["disposition"] == "MIGRATED_AS_ALIAS" for x in self.entries(led, text="RT1", **{"class": "LABEL"})))

    def test_an_explicit_decision_not_to_migrate_is_recorded_with_its_reason(self):
        self.mapping = self.mp(**{"micromap-findings:F11": {"disposition": "NOT_MIGRATED", "reason": "owner decided: not a requirement"}})
        e = at(self.build(), "v2", "L1", "F11")[0]
        self.assertEqual((e["disposition"], e["reason"]), ("NOT_MIGRATED", "owner decided: not a requirement"))

    def test_an_ambiguous_label_cannot_be_mapped_by_batch(self):
        self.mapping = self.mp(**{"plan-resolver-gaps-v1:R1": {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0001", "status": "HISTORICAL", "reason": "x"}})
        led = self.build()
        self.assertTrue(any("ambiguous" in p and "R1" in p for p in led["problems"]), led["problems"])
        self.assertFalse(led["complete"])
        self.assertNotIn("MIGRATED_AS_ALIAS", {e["disposition"] for e in led["entries"]})

    def test_a_label_that_exists_only_inside_a_range_cannot_be_mapped(self):
        self.mapping = self.mp(**{"micromap-resolver-gaps:RT2": {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0002", "status": "ACTIVE", "reason": "x"}})
        led = self.build()
        self.assertTrue(any("RT2" in p and "no occurrence" in p for p in led["problems"]), led["problems"])
        self.assertEqual([e for e in led["entries"] if e["text"] == "RT2"], [])

    def test_a_stale_mapping_entry_is_an_error_not_a_silent_no_op(self):
        self.mapping = self.mp(**{"micromap-resolver-gaps:RT9": {"disposition": "NOT_MIGRATED", "reason": "x"}})
        self.assertTrue(any("RT9" in p for p in self.build()["problems"]))

    def test_ambiguity_rules_make_a_single_namespace_label_ambiguous(self):
        self.amb = {"schema": "clx.ambiguity/1", "rules": [{"namespace": "bare-step-label", "meanings": ["a", "b"], "basis": "INVENTORY C-07"}]}
        led = self.build()
        e = at(led, "v1", "L3", "M3d", "LABEL")[0]
        self.assertEqual((e["disposition"], e["candidates"], e["meanings"]), ("AMBIGUOUS", ["bare-step-label"], ["a", "b"]))
        self.mapping = self.mp(**{"bare-step-label:M3d": {"disposition": "NOT_MIGRATED", "reason": "x"}})
        self.assertTrue(any("ambiguous" in p for p in self.build()["problems"]))

    def test_mapping_shape_errors_are_input_errors(self):
        good = {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0001", "status": "ACTIVE", "reason": "r"}
        bad = {
            "unknown namespace": ("nope:RT1", good), "value does not fit": ("micromap-resolver-gaps:Q1", good), "no colon": ("RT1", good),
            "bad disposition": ("micromap-resolver-gaps:RT1", dict(good, disposition="AMBIGUOUS")),
            "ambiguous disposition alone": ("micromap-resolver-gaps:RT1", {"disposition": "AMBIGUOUS", "reason": "r"}), "range disposition alone": ("micromap-resolver-gaps:RT1", {"disposition": "RANGE_NOT_EXPANDED", "reason": "r"}), "no reason": ("micromap-resolver-gaps:RT1", {k: v for k, v in good.items() if k != "reason"}),
            "empty reason": ("micromap-resolver-gaps:RT1", dict(good, reason="")), "no record": ("micromap-resolver-gaps:RT1", {k: v for k, v in good.items() if k != "record"}),
            "bad record id": ("micromap-resolver-gaps:RT1", dict(good, record="CLX-REQ-1")), "decision id as record": ("micromap-resolver-gaps:RT1", dict(good, record="CLX-DEC-0001")),
            "no status": ("micromap-resolver-gaps:RT1", {k: v for k, v in good.items() if k != "status"}), "bad status": ("micromap-resolver-gaps:RT1", dict(good, status="IMPLIED_BY_RANGE")),
            "record on not migrated": ("micromap-resolver-gaps:RT1", {"disposition": "NOT_MIGRATED", "reason": "r", "record": "CLX-REQ-0001"}),
            "unknown field": ("micromap-resolver-gaps:RT1", dict(good, x=1)),
        }
        for name, (k, v) in bad.items():
            with self.subTest(name):
                self.assertTrue(ledger.validate_mapping(self.mp(**{k: v}), self.ns), name)
                with self.assertRaises(ledger.LedgerInputError):
                    self.build(mapping=self.mp(**{k: v}))
        for top in (None, [], {"schema": "x", "tokens": {}}, {"schema": ledger.MAPPING_SCHEMA}, {"schema": ledger.MAPPING_SCHEMA, "tokens": []},
                    {"schema": ledger.MAPPING_SCHEMA, "tokens": {}, "x": 1}):
            self.assertTrue(ledger.validate_mapping(top, self.ns))


class SourceHandlingTests(Fx):
    def test_a_changed_source_is_detected_and_yields_no_entries_and_no_success(self):
        (self.ws / "a.md").write_bytes(self.files["a.md"] + b"changed\n")
        led = self.build()
        self.assertEqual(self.entries(led, version="v1"), [])
        self.assertEqual(led["sources"][0]["status"], "PROBLEM")
        self.assertTrue(any("doc/v1" in p and "pinned" in p for p in led["problems"]), led["problems"])
        self.assertFalse(led["complete"])

    def test_a_source_that_changes_during_the_import_is_detected(self):
        real = sources.read_verified
        calls = {"n": 0}

        def flaky(obj, roots, key, vid):
            data = real(obj, roots, key, vid)
            calls["n"] += 1
            if (key, vid) == ("doc", "v1") and calls["n"] >= 2:
                raise sources.SourceMismatch("doc changed between the two reads")
            return data

        with mock.patch.object(sources, "read_verified", flaky):
            led = self.build()
        self.assertEqual(self.entries(led, version="v1"), [])
        self.assertTrue(any("changed during the import" in p for p in led["problems"]), led["problems"])
        self.assertFalse(led["complete"])

    def test_a_missing_source_is_an_explicit_entry_and_the_ledger_is_not_complete(self):
        (self.ws / "b.md").unlink()
        led = self.build()
        e = self.entries(led, version="v2")
        self.assertEqual([(x["class"], x["disposition"]) for x in e], [("SOURCE", "SOURCE_MISSING")])
        self.assertEqual(e[0]["sha256"], sha(self.files["b.md"]))
        self.assertEqual(led["sources"][1]["status"], "MISSING")
        self.assertFalse(led["complete"])
        self.assertEqual(led["problems"], [])

    def test_an_unconfigured_root_is_a_missing_source_not_a_success(self):
        led = self.build(roots={})
        self.assertEqual({e["disposition"] for e in led["entries"]}, {"SOURCE_MISSING"})
        self.assertFalse(led["complete"])

    def test_an_unsupported_source_is_an_explicit_entry(self):
        data = b"PK\x03\x04"
        (self.ws / "c.docx").write_bytes(data)
        self.src["sources"][0]["versions"].append(srcver("v3", "c.docx", data))
        self.run["include"].append({"source": "doc", "version": "v3"})
        led = self.build()
        e = self.entries(led, version="v3")
        self.assertEqual([(x["class"], x["disposition"]) for x in e], [("SOURCE", "UNSUPPORTED")])
        self.assertIn(".docx", e[0]["reason"])
        self.assertEqual(led["sources"][2]["status"], "UNSUPPORTED")
        self.assertFalse(led["complete"])

    def test_a_source_that_is_not_utf8_is_unsupported_not_read_lossily(self):
        data = b"RT1 \xff\xfe"
        (self.ws / "c.md").write_bytes(data)
        self.src["sources"][0]["versions"].append(srcver("v3", "c.md", data))
        self.run["include"].append({"source": "doc", "version": "v3"})
        led = self.build()
        self.assertEqual([(x["class"], x["disposition"]) for x in self.entries(led, version="v3")], [("SOURCE", "UNSUPPORTED")])

    def test_an_excluded_source_needs_a_reason_and_a_decision_and_is_listed_not_scanned(self):
        self.run["include"] = [{"source": "doc", "version": "v1"}]
        self.run["excluded"] = [{"source": "doc", "version": "v2", "reason": "legacy copy", "decision": "owner message 2026-11-01"}]
        led = self.build()
        e = self.entries(led, version="v2")
        self.assertEqual([(x["class"], x["disposition"], x["reason"], x["decision"]) for x in e], [("SOURCE", "EXCLUDED", "legacy copy", "owner message 2026-11-01")])
        self.assertEqual(led["sources"][1]["status"], "EXCLUDED")
        self.assertTrue(led["complete"])

    def test_run_configuration_errors_are_input_errors(self):
        inc = lambda *v: [{"source": "doc", "version": x} for x in v]       # noqa: E731
        ex = {"source": "doc", "version": "v2", "reason": "r", "decision": "d"}
        bad = {
            "no include": dict(self.run, include=[]), "duplicate include": dict(self.run, include=inc("v1", "v1")),
            "unknown source": dict(self.run, include=[{"source": "nope", "version": "v1"}]), "unknown version": dict(self.run, include=inc("v9")),
            "included and excluded": dict(self.run, include=inc("v1", "v2"), excluded=[ex]),
            "excluded without reason": dict(self.run, include=inc("v1"), excluded=[{k: v for k, v in ex.items() if k != "reason"}]),
            "excluded empty decision": dict(self.run, include=inc("v1"), excluded=[dict(ex, decision="")]),
            "excluded duplicate": dict(self.run, include=inc("v1"), excluded=[ex, ex]), "excluded unknown": dict(self.run, include=inc("v1"), excluded=[dict(ex, version="v9")]),
            "wrong schema": dict(self.run, schema="x"), "unknown field": dict(self.run, x=1), "include not list": dict(self.run, include="doc"),
            "include item extra": dict(self.run, include=[{"source": "doc", "version": "v1", "x": 1}]),
        }
        for name, run in bad.items():
            with self.subTest(name):
                self.assertTrue(ledger.validate_run(run, self.src), name)
                with self.assertRaises(ledger.LedgerInputError):
                    self.build(run=run)

    def test_invalid_catalogs_are_input_errors(self):
        bad_src = copy.deepcopy(self.src)
        bad_src["sources"][0]["versions"][0]["sha256"] = "x"
        with self.assertRaises(ledger.LedgerInputError):
            self.build(src_cat=bad_src)
        bad_ns = copy.deepcopy(self.ns)
        bad_ns["namespaces"][0]["status"] = "x"
        with self.assertRaises(ledger.LedgerInputError):
            self.build(ns_obj=bad_ns)
        with self.assertRaises(ledger.LedgerInputError):
            self.build(amb_obj={"schema": "clx.ambiguity/1", "rules": [{"namespace": "nope", "meanings": ["a", "b"], "basis": "x"}]})

    def test_the_same_source_listed_twice_never_duplicates_records(self):
        self.run["include"].append({"source": "doc", "version": "v1"})
        with self.assertRaises(ledger.LedgerInputError):
            self.build()

    def test_sources_are_opened_read_only_and_unchanged(self):
        before = {n: ((self.ws / n).read_bytes(), (self.ws / n).stat().st_mtime_ns) for n in self.files}
        self.build()
        self.assertEqual(before, {n: ((self.ws / n).read_bytes(), (self.ws / n).stat().st_mtime_ns) for n in self.files})


class OdsSourceTests(Fx):
    def test_ods_cells_are_scanned_and_addressed(self):
        data = ods({"Plan": row(cell(p("RT1 is open")), cell(p("R1"))) + row(cell(), cell('<office:annotation><text:p>note RT3</text:p></office:annotation>' + p("x"))), "S2": row(cell(p("DONE")))})
        (self.ws / "r.ods").write_bytes(data)
        self.src["sources"][0]["versions"].append(srcver("v3", "r.ods", data))
        self.run["include"] = [{"source": "doc", "version": "v3"}]
        led = self.build()
        self.assertEqual([e["unit"] for e in led["entries"] if e["text"] == "RT1"], ["Plan!R1C1/p1"])
        self.assertEqual([e["unit"] for e in led["entries"] if e["text"] == "RT3"], ["Plan!R2C2/n1p1"])
        self.assertTrue(all("line" not in e for e in led["entries"]))
        self.assertEqual(ledger.verify_ledger(led, self.src, self.roots), [])


class ValidateAndVerifyTests(Fx):
    def test_a_good_ledger_verifies_against_its_sources(self):
        led = self.build()
        self.assertEqual(ledger.verify_ledger(led, self.src, self.roots), [])

    def test_tampering_with_an_entry_is_found(self):
        led = self.build()
        for mutate in (lambda e: e.update(text="RT9"), lambda e: e.update(column=e["column"] + 1), lambda e: e.update(unit="L99"),
                       lambda e: e.update(line=e["line"] + 1), lambda e: e.update(length=e["length"] + 1), lambda e: e.update(sha256="0" * 64)):
            bad = copy.deepcopy(led)
            mutate(next(e for e in bad["entries"] if e["text"] == "RT3"))
            with self.subTest():
                self.assertTrue(any(f.code == "DE-13" for f in ledger.verify_ledger(bad, self.src, self.roots)))

    def test_a_dropped_entry_is_found_through_the_coverage_map_and_counts(self):
        led = self.build()
        bad = copy.deepcopy(led)
        i = next(i for i, e in enumerate(bad["entries"]) if e["unit"] == "L7")
        del bad["entries"][i]
        codes = {f.code for f in ledger.verify_ledger(bad, self.src, self.roots) + ledger.validate_ledger(bad)}
        self.assertTrue(codes & {"DE-13", "DE-02"}, codes)

    def test_a_contained_match_at_a_wrong_location_is_found(self):
        led = self.build()
        bad = copy.deepcopy(led)
        next(e for e in bad["entries"] if e.get("contained"))["contained"][0]["column"] += 1
        self.assertTrue(any(f.code == "DE-13" and "contained" in f.message for f in ledger.verify_ledger(bad, self.src, self.roots)))

    def test_a_ledger_that_records_problems_does_not_verify(self):
        (self.ws / "a.md").write_bytes(b"changed")
        led = self.build()
        self.assertTrue(any(f.code == "DE-13" and "problem" in f.message for f in ledger.verify_ledger(led, self.src, self.roots)))

    def test_a_ledger_naming_another_hash_than_the_catalog_does_not_verify(self):
        led = self.build()
        bad = copy.deepcopy(led)
        bad["sources"][0]["sha256"] = "1" * 64
        self.assertTrue(any(f.code == "DE-13" and "another hash" in f.message for f in ledger.verify_ledger(bad, self.src, self.roots)))

    def test_a_wrong_coverage_map_is_found(self):
        led = self.build()
        bad = copy.deepcopy(led)
        bad["sources"][0]["uncovered_line_ranges"] = []
        self.assertTrue(any(f.code == "DE-13" and "coverage" in f.message for f in ledger.verify_ledger(bad, self.src, self.roots)))

    def test_a_ledger_with_a_silently_dropped_entry_differs_from_a_fresh_import(self):
        led = self.build()
        bad = copy.deepcopy(led)
        gone = next(i for i, e in enumerate(bad["entries"]) if e["unit"] == "L7")
        del bad["entries"][gone]
        for n, e in enumerate(bad["entries"], 1):               # renumbered and counted again: the entry-level checks cannot see it
            e["n"] = n
        bad["summary"]["entries"] -= 1
        bad["summary"]["dispositions"]["NOT_MIGRATED"] -= 1
        bad["summary"]["classes"]["LABEL"] -= 1
        inputs = dict(run=self.run, src_cat=self.src, ns_obj=self.ns, amb_obj=None, mapping=None, roots=self.roots)
        self.assertEqual(ledger.compare_with_rebuild(led, **inputs), [])
        f = ledger.compare_with_rebuild(bad, **inputs)
        self.assertEqual([x.code for x in f], ["DE-13"])
        self.assertIn("fresh import", f[0].message)

    def test_a_changed_source_is_found_at_verification(self):
        led = self.build()
        (self.ws / "a.md").write_bytes(b"other")
        self.assertTrue(any(f.code == "DE-13" for f in ledger.verify_ledger(led, self.src, self.roots)))

    def test_an_unavailable_source_is_advisory_never_a_pass_of_its_entries(self):
        led = self.build()
        f = ledger.verify_ledger(led, self.src, {})
        self.assertTrue(f and all(x.cls == "ADVISORY" and x.code == "AD-04" for x in f))

    @staticmethod
    def recount(l):
        """Keep the summary consistent with the entries, so that only the rule under test can fire."""
        by_d, by_c = {}, {}
        for e in l["entries"]:
            by_d[e["disposition"]] = by_d.get(e["disposition"], 0) + 1
            by_c[e["class"]] = by_c.get(e["class"], 0) + 1
        l["summary"].update(entries=len(l["entries"]), dispositions=by_d, classes=by_c)
        for n, e in enumerate(l["entries"], 1):
            e["n"] = n

    def test_structure_rules(self):
        led = self.build()
        first = lambda l, cls=None, d=None: next(e for e in l["entries"] if (cls is None or e["class"] == cls) and (d is None or e["disposition"] == d))      # noqa: E731
        bad = {
            "unknown disposition": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(disposition="GUESSED"),
            "unknown class": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(**{"class": "X"}),
            "record on a range": lambda l: first(l, "RANGE").update(record="CLX-REQ-0001"),
            "record on a label that is not migrated": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(record="CLX-REQ-0001"),
            "status on a label that is not migrated": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(status="ACTIVE"),
            "migrated without record": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(disposition="MIGRATED_AS_ALIAS", status="ACTIVE"),
            "migrated without status": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(disposition="MIGRATED_AS_ALIAS", record="CLX-REQ-0001"),
            "migrated with a bad record id": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(disposition="MIGRATED_AS_ALIAS", record="CLX-REQ-1", status="ACTIVE"),
            "ambiguous with a namespace": lambda l: first(l, "LABEL", "AMBIGUOUS").update(namespace="risk-classes"),
            "ambiguous with a record": lambda l: first(l, "LABEL", "AMBIGUOUS").update(record="CLX-REQ-0001"),
            "ambiguous without candidates": lambda l: first(l, "LABEL", "AMBIGUOUS").pop("candidates"),
            "ambiguous with empty candidates": lambda l: first(l, "LABEL", "AMBIGUOUS").update(candidates=[]),
            "label without its namespace": lambda l: first(l, "LABEL", "NOT_MIGRATED").pop("namespace"),
            "label with a range disposition": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(disposition="RANGE_NOT_EXPANDED"),
            "label with a source-level disposition": lambda l: first(l, "LABEL", "NOT_MIGRATED").update(disposition="EXCLUDED"),
            "state word with another disposition": lambda l: first(l, "STATE_WORD").update(disposition="NOT_MIGRATED"),
            "range with another disposition": lambda l: first(l, "RANGE").update(disposition="NOT_MIGRATED"),
            "unclassified with another disposition": lambda l: first(l, "UNCLASSIFIED").update(disposition="NOT_MIGRATED"),
            "migrated range": lambda l: first(l, "RANGE").update(disposition="MIGRATED_AS_ALIAS", record="CLX-REQ-0001", status="ACTIVE"),
            "duplicate entry": lambda l: l["entries"].append(dict(l["entries"][0])),
            "empty text": lambda l: first(l, "LABEL").update(text=""),
            "wrong length": lambda l: first(l, "LABEL").update(length=99),
            "no column": lambda l: first(l, "LABEL").update(column=0),
            "no reason": lambda l: first(l, "LABEL").pop("reason"),
        }
        for name, mutate in bad.items():
            b = copy.deepcopy(led)
            mutate(b)
            self.recount(b)
            with self.subTest(name):
                self.assertTrue(ledger.validate_ledger(b), name)
        self.assertEqual(ledger.validate_ledger(led), [])
        for name, mutate in {"wrong schema": lambda l: l.update(schema="x"), "n out of sequence": lambda l: l["entries"][1].update(n=99),
                             "summary mismatch": lambda l: l["summary"].update(entries=1), "summary classes mismatch": lambda l: l["summary"]["classes"].update(LABEL=1),
                             "complete although problems": lambda l: l.update(problems=["x"]), "entries not a list": lambda l: l.update(entries={}),
                             "not an object": None}.items():
            b = copy.deepcopy(led)
            if mutate is None:
                b = []
            else:
                mutate(b)
            with self.subTest(name):
                self.assertTrue(ledger.validate_ledger(b), name)

    def test_source_level_entries_follow_their_own_rules(self):
        (self.ws / "b.md").unlink()
        self.run["excluded"] = []
        led = self.build()
        self.assertEqual(ledger.validate_ledger(led), [])
        miss = next(e for e in led["entries"] if e["class"] == "SOURCE")
        for name, mutate in {"another disposition": lambda e: e.update(disposition="NOT_MIGRATED"), "a token disposition": lambda e: e.update(disposition="AMBIGUOUS"),
                             "no reason": lambda e: e.pop("reason")}.items():
            b = copy.deepcopy(led)
            mutate(next(e for e in b["entries"] if e["class"] == "SOURCE"))
            self.recount(b)
            with self.subTest(name):
                self.assertTrue(ledger.validate_ledger(b), name)
        self.assertEqual(miss["disposition"], "SOURCE_MISSING")

    def test_an_exclusion_without_its_decision_is_invalid(self):
        self.run["include"] = [{"source": "doc", "version": "v1"}]
        self.run["excluded"] = [{"source": "doc", "version": "v2", "reason": "r", "decision": "d"}]
        led = self.build()
        self.assertEqual(ledger.validate_ledger(led), [])
        b = copy.deepcopy(led)
        next(e for e in b["entries"] if e["disposition"] == "EXCLUDED").pop("decision")
        self.assertTrue(ledger.validate_ledger(b))


class DiffTests(Fx):
    def test_identical_ledgers_have_no_difference(self):
        d = ledger.diff_ledgers(self.build(), self.build())
        self.assertEqual((d["added"], d["removed"], d["changed"]), ([], [], []))

    def test_a_mapping_changes_exactly_the_mapped_entries(self):
        before = self.build()
        self.mapping = {"schema": ledger.MAPPING_SCHEMA, "tokens": {"micromap-resolver-gaps:RT1": {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0001", "status": "ACTIVE", "reason": "r"}}}
        after = self.build()
        d = ledger.diff_ledgers(before, after)
        self.assertEqual((d["added"], d["removed"]), ([], []))
        self.assertEqual({(c["text"], c["unit"]) for c in d["changed"]}, {("RT1", "L2"), ("RT1", "L7")})
        self.assertEqual(len(d["changed"]), len([e for e in after["entries"] if e["text"] == "RT1" and e["class"] == "LABEL"]))
        self.assertEqual(d["changed"][0]["before"]["disposition"], "NOT_MIGRATED")
        self.assertEqual(d["changed"][0]["after"]["disposition"], "MIGRATED_AS_ALIAS")

    def test_a_changed_source_shows_as_added_and_removed_entries(self):
        before = self.build()
        text = A_MD.replace("RT1 RT1 RT1", "RT1 RT1")
        (self.ws / "a.md").write_bytes(text.encode("utf-8"))
        self.src["sources"][0]["versions"][0] = srcver("v1", "a.md", text.encode("utf-8"))
        d = ledger.diff_ledgers(before, self.build())
        self.assertEqual([r["text"] for r in d["removed"]], ["RT1"])
        self.assertEqual(d["added"], [])
        self.assertTrue(d["sources_changed"])

    def test_entries_only_in_the_second_ledger_are_reported_as_added(self):
        full = self.build()
        text = A_MD.replace("RT1 RT1 RT1", "RT1 RT1")
        (self.ws / "a.md").write_bytes(text.encode("utf-8"))
        self.src["sources"][0]["versions"][0] = srcver("v1", "a.md", text.encode("utf-8"))
        less = self.build()
        d = ledger.diff_ledgers(less, full)
        self.assertEqual([a["text"] for a in d["added"]], ["RT1"])
        self.assertEqual(d["removed"], [])

    def test_diff_is_sorted_and_does_not_modify_its_inputs(self):
        a, b = self.build(), self.build(mapping={"schema": ledger.MAPPING_SCHEMA, "tokens": {"micromap-findings:F11": {"disposition": "NOT_MIGRATED", "reason": "r"}}})
        ca, cb = copy.deepcopy(a), copy.deepcopy(b)
        d = ledger.diff_ledgers(a, b)
        self.assertEqual((a, b), (ca, cb))
        self.assertEqual(d, ledger.diff_ledgers(a, b))


class CliTests(Fx):
    def write(self, name, obj):
        p_ = self.d / name
        canon.write_record(p_, obj, overwrite=True)
        return str(p_)

    def args(self, out):
        a = ["build", "--run", self.write("run.json", self.run), "--catalog", self.write("src.json", self.src), "--namespaces", self.write("ns.json", self.ns),
             "--root", f"ws={self.ws}", "--out", str(out)]
        return a

    def cli(self, *argv):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = ledger.main(list(argv))
        return code, o.getvalue(), e.getvalue()

    def test_build_writes_a_canonical_ledger_twice_byte_identically_and_refuses_overwrite(self):
        out1, out2 = self.d / "l1.json", self.d / "l2.json"
        c1, o1, _ = self.cli(*self.args(out1))
        self.assertEqual(c1, 0, o1)
        self.assertIn("complete", o1)
        self.assertEqual(self.cli(*self.args(out2))[0], 0)
        self.assertEqual(out1.read_bytes(), out2.read_bytes())
        self.assertTrue(canon.is_canonical(out1.read_text(encoding="utf-8")))
        c3, _, e3 = self.cli(*self.args(out1))
        self.assertEqual(c3, 3)
        self.assertIn("exist", e3)

    def test_exit_codes_for_problems_and_incomplete_runs(self):
        (self.ws / "a.md").write_bytes(b"changed")
        self.assertEqual(self.cli(*self.args(self.d / "p.json"))[0], 1)
        (self.ws / "a.md").write_bytes(self.files["a.md"])
        (self.ws / "b.md").unlink()
        code, out, _ = self.cli(*self.args(self.d / "i.json"))
        self.assertEqual(code, 2)
        self.assertIn("INCOMPLETE", out)

    def test_an_input_that_is_not_canonical_is_refused(self):
        args = self.args(self.d / "n.json")
        (self.d / "run.json").write_text(json.dumps(self.run, indent=4), encoding="utf-8")
        code, _, err = self.cli(*args)
        self.assertEqual(code, 3)
        self.assertIn("canonical", err)

    def test_the_ledger_records_digests_of_every_input(self):
        base = self.build()["inputs"]
        self.assertEqual(set(base), {"tool", "run_digest", "catalog_digest", "namespaces_digest"})
        self.mapping = {"schema": ledger.MAPPING_SCHEMA, "tokens": {"micromap-findings:F11": {"disposition": "NOT_MIGRATED", "reason": "r"}}}
        self.amb = {"schema": "clx.ambiguity/1", "rules": [{"namespace": "bare-step-label", "meanings": ["a", "b"], "basis": "x"}]}
        full = self.build()["inputs"]
        self.assertEqual({"mapping_digest", "ambiguity_digest"} - set(full), set())
        self.assertEqual(full["mapping_digest"], canon.digest(self.mapping))
        self.assertEqual(full["ambiguity_digest"], canon.digest(self.amb))
        self.assertEqual((full["run_digest"], full["catalog_digest"], full["namespaces_digest"]), (base["run_digest"], base["catalog_digest"], base["namespaces_digest"]))
        self.assertEqual(base["catalog_digest"], canon.digest(self.src))

    def test_unusable_inputs_exit_3(self):
        self.run["include"] = []
        self.assertEqual(self.cli(*self.args(self.d / "x.json"))[0], 3)
        self.assertEqual(self.cli("build", "--run", str(self.d / "none.json"), "--catalog", "a", "--namespaces", "b", "--out", str(self.d / "y.json"))[0], 3)

    def test_verify_and_diff_commands(self):
        out = self.d / "l.json"
        self.cli(*self.args(out))
        code, o, _ = self.cli("verify", "--ledger", str(out), "--catalog", str(self.d / "src.json"), "--root", f"ws={self.ws}")
        self.assertEqual(code, 0, o)
        (self.ws / "a.md").write_bytes(b"x")
        self.assertEqual(self.cli("verify", "--ledger", str(out), "--catalog", str(self.d / "src.json"), "--root", f"ws={self.ws}")[0], 1)
        code, o, _ = self.cli("diff", str(out), str(out))
        self.assertEqual(code, 0)
        self.assertIn("no difference", o)

    def test_verify_with_a_rebuild_finds_a_ledger_that_is_not_what_the_inputs_give(self):
        out = self.d / "l.json"
        self.cli(*self.args(out))
        led = json.loads(out.read_text(encoding="utf-8"))
        led["entries"][-1]["reason"] = "edited by hand"
        tampered = self.d / "t.json"
        canon.write_record(tampered, led)
        base = ["verify", "--catalog", str(self.d / "src.json"), "--root", f"ws={self.ws}"]
        self.assertEqual(self.cli(*base, "--ledger", str(tampered))[0], 0)             # the entry-level checks cannot see a changed reason
        code, o, _ = self.cli(*base, "--ledger", str(tampered), "--run", str(self.d / "run.json"), "--namespaces", str(self.d / "ns.json"))
        self.assertEqual(code, 1)
        self.assertIn("fresh import", o)
        self.assertEqual(self.cli(*base, "--ledger", str(out), "--run", str(self.d / "run.json"), "--namespaces", str(self.d / "ns.json"))[0], 0)

    def test_diff_of_different_ledgers_exits_1(self):
        out = self.d / "l.json"
        self.cli(*self.args(out))
        led = json.loads(out.read_text(encoding="utf-8"))
        next(e for e in led["entries"] if e["disposition"] == "NOT_MIGRATED").update(disposition="UNCLASSIFIED_LABEL")
        other = self.d / "m.json"
        canon.write_record(other, led)
        code, o, _ = self.cli("diff", str(out), str(other))
        self.assertEqual(code, 1)
        self.assertIn("changed: 1", o)


if __name__ == "__main__":
    unittest.main()
