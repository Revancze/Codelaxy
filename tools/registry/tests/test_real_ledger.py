"""S1 on the REAL sources (MICROMAP rev. 1, the ratified rev. 2 bytes, the ratification record): needs machine-local data, otherwise NOT RUN with the reason."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from clxreg import candidates, canon, ledger, store
from tests.test_sources import LOCAL, _real_roots, _real_skip_reason

SPECS = Path(__file__).resolve().parent.parent / "catalog-specs"
GOLDEN_LEDGER_SHA256 = "52ebaa58f2b8e34c7acc2fd8491580efed1644903e444d619a24148180bc3a63"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


@unittest.skipIf(_real_skip_reason(), _real_skip_reason() or "")
class RealLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roots = {"workspace": _real_roots()["workspace"]}       # only the root the catalog uses: the others (e.g. the home folder) would contain every scratch directory
        cls.src = load(LOCAL / "sources.json")
        cls.cfg, cls.ns, cls.amb = load(SPECS / "run.micromap.json"), load(SPECS / "namespaces.micromap.json"), load(SPECS / "ambiguity.micromap.json")
        cls.led = ledger.build_ledger(cls.cfg, cls.src, cls.ns, cls.amb, None, cls.roots)

    def test_the_import_is_complete_and_verifies_against_the_pinned_bytes(self):
        self.assertTrue(self.led["complete"], self.led["problems"])
        self.assertEqual(ledger.validate_ledger(self.led), [])
        self.assertEqual(ledger.verify_ledger(self.led, self.src, self.roots), [])
        self.assertEqual(ledger.compare_with_rebuild(self.led, self.cfg, self.src, self.ns, self.amb, None, self.roots), [])

    def test_the_ledger_is_byte_identical_on_every_machine(self):
        digest = hashlib.sha256(canon.dumps(self.led).encode("utf-8")).hexdigest()
        self.assertEqual(digest, GOLDEN_LEDGER_SHA256, "the real ledger changed: review the difference with `ledger diff`, then update the golden value")

    def test_rt2_is_never_an_entry_but_the_range_and_its_ends_are(self):
        self.assertEqual([e for e in self.led["entries"] if e["text"] == "RT2"], [])
        ranges = [e for e in self.led["entries"] if e["class"] == "RANGE" and e["text"].startswith("RT1")]
        self.assertTrue(ranges and all(e["disposition"] == "RANGE_NOT_EXPANDED" and e["ends"] == ["RT1", "RT3"] for e in ranges))
        for label in ("RT1", "RT3"):
            self.assertTrue([e for e in self.led["entries"] if e["text"] == label and e["class"] == "LABEL" and e["version"] == "ratified-bytes"])

    def test_counts_equal_an_independent_count_straight_from_the_bytes(self):
        def word(c):
            return c.isalnum() or c == "_"

        def count(text, s):
            n, i = 0, 0
            while True:
                i = text.find(s, i)
                if i < 0:
                    return n
                if not (i > 0 and word(text[i - 1])) and not (i + len(s) < len(text) and word(text[i + len(s)])):
                    n += 1
                i += 1

        files = {"revision-1": "proposals/backup/MICROMAP.revision-1.2026-10-18.md", "ratified-bytes": "proposals/backup/MICROMAP.revision-2-ratified-content.2026-10-25.md",
                 "2026-10-25": "proposals/docs/MICROMAP.RATIFICATION-2026-10-25.md"}
        for ver, rel in files.items():
            text = (Path(self.roots["workspace"]) / rel).read_bytes().decode("utf-8")
            ents = [e for e in self.led["entries"] if e.get("version") == ver]
            for s in ("RT1", "RT3", "F11", "MD5", "MO3", "RUN-3", "E1-7", "A-MUT-3", "M1-GA", "MSYS2-COMPAT", "P1.2-M3d", "M3d", "R1", "R4", "DONE", "OPEN", "PASS", "PLANNED"):
                got = sum(1 for e in ents if e["text"] == s) + sum(1 for e in ents for c in e.get("contained", []) if c["text"] == s)
                with self.subTest(version=ver, token=s):
                    self.assertEqual(got, count(text, s))

    def test_the_same_label_of_two_namespaces_stays_ambiguous_and_unmerged(self):
        r1 = [e for e in self.led["entries"] if e["text"] == "R1" and e["class"] == "LABEL"]
        self.assertTrue(r1)
        self.assertTrue(all(e["disposition"] == "AMBIGUOUS" and e["candidates"] == ["branching-risk-classes", "plan-resolver-gaps-v1"] for e in r1))
        self.assertFalse([e for e in self.led["entries"] if e["disposition"] == "AMBIGUOUS" and ("record" in e or "namespace" in e)])
        bare = [e for e in self.led["entries"] if e["class"] == "LABEL" and e.get("candidates") == ["bare-step-label"]]
        self.assertTrue(bare and all(e["meanings"] and e["disposition"] == "AMBIGUOUS" for e in bare))

    def test_states_references_and_results_are_all_recorded_literally(self):
        classes = self.led["summary"]["classes"]
        for c in ("STATE_WORD", "REFERENCE", "RESULT_PHRASE"):
            self.assertGreater(classes.get(c, 0), 0, c)
        for e in self.led["entries"]:
            if e["class"] in ("STATE_WORD", "REFERENCE", "RESULT_PHRASE"):
                self.assertEqual(e["disposition"], "UNCLASSIFIED_LABEL")

    def test_nothing_is_dropped_the_coverage_map_accounts_for_every_line(self):
        for s in self.led["sources"]:
            self.assertEqual(s["status"], "PROCESSED")
            self.assertEqual(s["units_with_entries"] + s["uncovered_count"] + s["blank_units"], s["units"])
            self.assertEqual(sum(b - a + 1 for a, b in s["uncovered_line_ranges"]), s["uncovered_count"])

    def test_a_dry_run_of_candidates_from_the_real_sources_in_a_scratch_store(self):
        with tempfile.TemporaryDirectory() as d:
            reg, out = Path(d) / "reg", Path(d) / "out"
            for t in store.STORED_TYPES:
                (reg / "records" / t).mkdir(parents=True)
            canon.write_record(reg / "records" / "REQ" / "CLX-REQ-0001.json", {"schema_version": 1, "id": "CLX-REQ-0001", "type": "REQ", "title": "scratch"})
            mapping = {"schema": ledger.MAPPING_SCHEMA, "tokens": {
                "micromap-resolver-gaps:RT1": {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0001", "status": "ACTIVE", "reason": "scratch dry-run"},
                "micromap-resolver-gaps:RT3": {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0001", "status": "ACTIVE", "reason": "scratch dry-run"}}}
            m = candidates.generate(self.cfg, self.src, self.ns, self.amb, mapping, self.roots, reg, out)
            self.assertEqual(m["mapped"], ["micromap-resolver-gaps:RT1", "micromap-resolver-gaps:RT3"])
            c = load(out / "aliases" / "CLX-REQ-0001.json")
            self.assertEqual([(a["value"], a["source"]["version"]) for a in c["aliases"]], [("RT1", "ratified-bytes"), ("RT3", "ratified-bytes")])
            self.assertEqual(len(c["origins"][0]["occurrences"]), 7)
            mapping["tokens"]["micromap-resolver-gaps:RT2"] = copy.deepcopy(mapping["tokens"]["micromap-resolver-gaps:RT1"])
            with self.assertRaises(candidates.CandidateError):
                candidates.generate(self.cfg, self.src, self.ns, self.amb, mapping, self.roots, reg, Path(d) / "out2")
            mapping["tokens"].pop("micromap-resolver-gaps:RT2")
            mapping["tokens"]["branching-risk-classes:R1"] = {"disposition": "MIGRATED_AS_ALIAS", "record": "CLX-REQ-0001", "status": "HISTORICAL", "reason": "x"}
            with self.assertRaises(candidates.CandidateError) as cm:
                candidates.generate(self.cfg, self.src, self.ns, self.amb, mapping, self.roots, reg, Path(d) / "out3")
            self.assertIn("ambiguous", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
