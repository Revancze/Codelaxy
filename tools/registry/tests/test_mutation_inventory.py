"""The mutant inventory (mutation/inventory.py): the shipped specs are statically sound, and reports can neither be built from stale results nor hide a gap (tier B)."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("clx_mutation_inventory", ROOT / "mutation" / "inventory.py")
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)


def mutant(mid="X01", **o):
    m = {"id": mid, "file": "m.py", "old": "a = 1", "new": "a = 2", "note": "changes a"}
    m.update(o)
    return m


class Tree:
    def __init__(self, test):
        self._t = tempfile.TemporaryDirectory()
        test.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_x.py").write_text("", encoding="utf-8")
        (self.root / "m.py").write_text("a = 1\nb = 2\n", encoding="utf-8")

    def check(self, specs, retired=()):
        return inv.check(specs, list(retired), self.root)


def spec(*mutants, tests=("tests.test_x",)):
    return {"tests": list(tests), "mutants": list(mutants)}


class ShippedSpecsTests(unittest.TestCase):
    def test_every_shipped_spec_is_statically_sound(self):
        specs = inv.load_specs()
        retired = json.loads(inv.RETIRED.read_text(encoding="utf-8"))["retired"]
        self.assertEqual(inv.check(specs, retired), [])

    def test_there_are_specs_and_ids_are_unique(self):
        specs = inv.load_specs()
        ids = [m["id"] for s in specs.values() for m in s["mutants"]]
        self.assertGreater(len(ids), 500)
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_equivalence_claim_has_a_reason(self):
        claims = {m["id"]: m["equivalent"] for s in inv.load_specs().values() for m in s["mutants"] if "equivalent" in m}
        self.assertTrue({"C04", "C06", "S24", "S37", "CA26", "CA27"} <= set(claims))
        for mid, why in claims.items():
            self.assertGreaterEqual(len(why), 20, mid)


class CheckTests(unittest.TestCase):
    def test_a_sound_spec_has_no_problems(self):
        self.assertEqual(Tree(self).check({"s": spec(mutant())}), [])

    def test_each_defect_is_named(self):
        t = Tree(self)
        cases = {
            "duplicate id": ({"s": spec(mutant("X01"), mutant("X01"))}, "used in both"),
            "id shared by two specs": ({"s": spec(mutant("X01")), "t": spec(mutant("X01"))}, "unique across all specs"),
            "pattern absent": ({"s": spec(mutant(old="zzz"))}, "occurs 0 times"),
            "pattern twice": ({"s": spec(mutant(old="= "))}, "occurs 2 times"),
            "no-op mutation": ({"s": spec(mutant(new="a = 1"))}, "changes nothing"),
            "missing note": ({"s": spec(mutant(note=""))}, "'note' missing or empty"),
            "missing file": ({"s": spec(mutant(file="nothing.py"))}, "does not exist"),
            "missing test module": ({"s": spec(mutant(), tests=("tests.test_nothing",))}, "test module"),
            "reasonless equivalence": ({"s": spec(mutant(equivalent="short"))}, "needs a reason"),
            "malformed platform_specific": ({"s": spec(mutant(platform_specific={"survives_on": []}))}, "platform_specific must be"),
            "both declarations": ({"s": spec(mutant(equivalent="x" * 30, platform_specific={"survives_on": ["linux"], "reason": "r"}))}, "both equivalent and platform_specific"),
        }
        for name, (specs, text) in cases.items():
            with self.subTest(name):
                self.assertTrue(any(text in p for p in t.check(specs)), t.check(specs))

    def test_a_retired_id_is_never_reused(self):
        t = Tree(self)
        problems = t.check({"s": spec(mutant("X01"))}, [{"id": "X01", "spec": "s", "reason": "withdrawn"}])
        self.assertTrue(any("retired" in p for p in problems))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.specs_dir = self.d / "specs"
        self.res = self.d / "res"
        self.specs_dir.mkdir()
        self.res.mkdir()
        self.specs = {"s": spec(mutant("X01"), mutant("X02", equivalent="the change cannot be seen by any test"), mutant("X03"))}
        (self.specs_dir / "s.json").write_text(json.dumps(self.specs["s"]), encoding="utf-8")
        self.sha = hashlib.sha256((self.specs_dir / "s.json").read_bytes()).hexdigest()

    def result(self, statuses, platform="windows", sha=None, name="s.json", ids=("X01", "X02", "X03")):
        r = {"platform": platform, "python": "3.15", "spec": "s.json", "spec_sha256": sha or self.sha, "tests": ["tests.test_x"],
             "results": [{"id": i, "status": s} for i, s in zip(ids, statuses)]}
        (self.res / name).write_text(json.dumps(r), encoding="utf-8")

    def report(self):
        return inv.report(self.specs, [], [self.res], self.specs_dir)

    def test_a_clean_result_has_no_problems_and_exact_totals(self):
        self.result(["KILLED", "SURVIVED-EQUIVALENT", "KILLED"])
        md, problems = self.report()
        self.assertEqual(problems, [])
        self.assertIn("| KILLED | 2 |", md)
        self.assertIn("| SURVIVED-EQUIVALENT | 1 |", md)
        self.assertIn("| SURVIVED-GAP | 0 |", md)

    def test_a_result_for_another_version_of_the_spec_is_refused(self):
        self.result(["KILLED"] * 3, sha="0" * 64)
        md, problems = self.report()
        self.assertTrue(any("stale" in p for p in problems))
        self.assertNotIn("windows", md)                                         # nothing from the stale file reached the table

    def test_a_result_that_does_not_cover_the_spec_is_refused(self):
        self.result(["KILLED", "KILLED"], ids=("X01", "X02"))
        _, problems = self.report()
        self.assertTrue(any("do not cover exactly" in p for p in problems))

    def test_a_surviving_mutant_without_a_declaration_is_a_problem(self):
        self.result(["SURVIVED-EQUIVALENT", "SURVIVED-EQUIVALENT", "KILLED"])
        _, problems = self.report()
        self.assertEqual([p for p in problems if "survived without a declaration" in p], ["s/X01 ('windows', '3.15'): survived without a declaration"])

    def test_a_test_gap_is_a_problem(self):
        self.result(["SURVIVED-GAP", "SURVIVED-EQUIVALENT", "KILLED"])
        _, problems = self.report()
        self.assertTrue(any("X01" in p and "SURVIVED-GAP" in p for p in problems))

    def test_a_result_for_an_unknown_spec_is_refused(self):
        r = {"platform": "windows", "python": "3.15", "spec": "ghost.json", "spec_sha256": self.sha, "tests": [], "results": []}
        (self.res / "ghost.json").write_text(json.dumps(r), encoding="utf-8")
        _, problems = self.report()
        self.assertTrue(any("unknown spec" in p for p in problems))

    def test_a_platform_with_only_some_specs_run_shows_the_rest_as_not_run(self):
        self.specs["t"] = spec(mutant("Y01"))
        (self.specs_dir / "t.json").write_text(json.dumps(self.specs["t"]), encoding="utf-8")
        self.result(["KILLED", "SURVIVED-EQUIVALENT", "KILLED"])
        md, problems = self.report()
        self.assertEqual(problems, [])
        self.assertIn("| t | Y01 | m.py |  | NOT RUN |", md)


if __name__ == "__main__":
    unittest.main()
