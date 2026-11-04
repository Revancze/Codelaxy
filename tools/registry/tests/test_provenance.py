"""IMP2-11 (b) - provenance checklist of a DIRTY run: PROVISIONAL needs all six points proven, otherwise the evidence is UNBOUND with the names (tier A)."""
import copy
import unittest

from clxreg import provenance as pv

H = "227733484a1851bc512f7ba3fef6dd78b6d0e5da"
M = "a" * 64


def good():
    return {
        "record": {"run_id": "3f1ad39e", "stamp": "20261101-160858", "head": H, "platform": "win", "timestamp": "2026-11-01T16:12:09"},
        "run_dir": {"name": "Codelaxy-m3d-20261101-160858-3f1ad39e-win", "id": "3f1ad39e", "stamp": "20261101-160858", "platform": "win"},
        "trx": {"present": True, "start": "2026-11-01T16:09:37.6677643+01:00", "finish": "2026-11-01T16:12:09.0855674+01:00",
                "tests": {"Codelaxy.Tests.A.B": ["Passed"]}},
        "copy": {"exists": True, "name": "Codelaxy-m3d-win-20261101-160858-3f1ad39e", "id": "3f1ad39e", "stamp": "20261101-160858", "platform": "win", "has_git": False, "head": None},
        "manifest_at_run": {"kind": "tree", "digest": M, "captured_at": "2026-11-01T16:09:00", "excludes": ["bin", "obj"], "head": H},
        "manifest_now": {"kind": "tree", "digest": M, "excludes": ["bin", "obj"]},
        "environment": {"utc_offset": "+01:00", "trx_prefix": "win", "record_environment": "Windows · git 2.56.0 · dotnet 10.0.113", "env_file_os": None},
        "test": {"name": "Codelaxy.Tests.A.B", "guard": "NOT_LISTED_COMPLETE_LIST"},
    }


def broken(path, value):
    f = good()
    d = f
    for k in path[:-1]:
        d = d[k]
    if value is pv_DELETE:
        del d[path[-1]]
    else:
        d[path[-1]] = value
    return f


pv_DELETE = object()


class AssessmentTests(unittest.TestCase):
    def test_all_six_points_proven(self):
        a = pv.assess(good())
        self.assertTrue(a.proven)
        self.assertEqual(a.unmet, ())
        self.assertEqual([(p.n, p.name, p.holds) for p in a.points], [(1, "run-identity", True), (2, "head", True), (3, "manifest-at-run", True),
                                                                      (4, "platform-environment", True), (5, "copy-unchanged", True), (6, "test-executed", True)])
        self.assertTrue(all(p.basis for p in a.points))

    def test_each_point_taken_away_alone_gives_exactly_that_name(self):
        cases = {
            "run-identity": broken(["run_dir", "id"], "deadbeef"),
            "manifest-at-run": broken(["manifest_at_run", "captured_at"], "2026-11-01T16:10:00"),
            "platform-environment": broken(["environment", "trx_prefix"], "linux"),
            "copy-unchanged": broken(["manifest_now", "digest"], "b" * 64),
            "test-executed": broken(["test", "guard"], "LISTED"),
        }
        f = good()
        f["copy"]["head"] = "f" * 40
        f["manifest_at_run"]["head"] = "f" * 40
        cases["head"] = f
        for name, facts in cases.items():
            a = pv.assess(facts)
            with self.subTest(name):
                self.assertFalse(a.proven)
                self.assertEqual(a.unmet, (name,))

    def test_identity_details(self):
        for path, value in ((["record", "run_id"], "00000000"), (["copy", "id"], "00000000"), (["run_dir", "stamp"], "20261101-000000"), (["copy", "stamp"], "20261101-000000"),
                            (["record", "platform"], "linux"), (["copy", "platform"], "linux"), (["trx", "finish"], "2026-11-01T16:13:00+01:00"),
                            (["trx", "finish"], "2026-10-31T16:10:00+01:00"), (["trx", "present"], False), (["record", "run_id"], ""), (["record", "timestamp"], "yesterday")):
            f = broken(path, value)
            with self.subTest(path=path, value=value):
                self.assertIn("run-identity", pv.assess(f).unmet)

    def test_a_trx_that_finished_before_it_started_or_on_another_day_than_the_record(self):
        f = good()
        f["trx"]["start"] = "2026-11-01T16:13:00+01:00"
        self.assertEqual(pv.assess(f).unmet, ("run-identity",))
        f = good()
        f["record"]["timestamp"] = "2026-11-02T02:10:00"  # a different UTC day too
        self.assertEqual(pv.assess(f).unmet, ("run-identity",))
        f = good()
        f["trx"]["finish"] = None
        self.assertEqual(pv.assess(f).unmet, ("run-identity",))

    def test_the_trx_must_have_finished_before_the_record_was_written(self):
        f = good()
        f["record"]["timestamp"] = "2026-11-01T16:12:09"          # equal to the finish: allowed
        self.assertTrue(pv.assess(f).proven)
        f["record"]["timestamp"] = "2026-11-01T16:12:08"
        self.assertIn("run-identity", pv.assess(f).unmet)

    def test_head_must_be_known_and_equal(self):
        f = good()
        f["manifest_at_run"].pop("head")
        self.assertIn("head", pv.assess(f).unmet)                  # a copy without .git carries no head of its own
        f["copy"]["has_git"], f["copy"]["head"] = True, H
        self.assertTrue(pv.assess(f).proven)
        f["copy"]["head"] = H[:7]
        self.assertIn("head", pv.assess(f).unmet)                  # a prefix is not a head
        f = good()
        f["record"]["head"] = "x"
        self.assertIn("head", pv.assess(f).unmet)

    def test_a_manifest_captured_at_the_start_of_the_run_counts_one_captured_later_does_not(self):
        f = good()
        f["manifest_at_run"]["captured_at"] = "2026-11-01T16:09:37"
        self.assertNotIn("manifest-at-run", pv.assess(f).unmet)
        f["manifest_at_run"]["captured_at"] = "2026-11-01T16:09:38"
        self.assertIn("manifest-at-run", pv.assess(f).unmet)
        f = good()
        f["manifest_at_run"]["digest"] = "short"
        self.assertIn("manifest-at-run", pv.assess(f).unmet)
        f = good()
        f["manifest_at_run"] = None
        a = pv.assess(f)
        self.assertEqual(set(a.unmet), {"head", "manifest-at-run", "copy-unchanged"})       # no manifest: nothing else can be shown either

    def test_two_missing_manifests_do_not_make_a_copy_unchanged(self):
        f = good()
        f["manifest_at_run"], f["manifest_now"] = None, None
        self.assertIn("copy-unchanged", pv.assess(f).unmet)
        f = good()
        f["manifest_at_run"]["digest"], f["manifest_now"]["digest"] = None, None
        self.assertIn("copy-unchanged", pv.assess(f).unmet)

    def test_the_copy_must_be_unchanged_by_the_same_rule_of_exclusions(self):
        f = good()
        f["manifest_now"]["excludes"] = []
        self.assertEqual(pv.assess(f).unmet, ("copy-unchanged",))
        f = good()
        f["manifest_now"]["kind"] = "git-dirty"
        self.assertEqual(pv.assess(f).unmet, ("copy-unchanged",))
        f = good()
        f["manifest_now"] = None
        self.assertEqual(pv.assess(f).unmet, ("copy-unchanged",))
        f = good()
        f["copy"]["exists"] = False
        self.assertIn("copy-unchanged", pv.assess(f).unmet)

    def test_a_record_without_an_environment_or_with_a_foreign_one(self):
        f = good()
        f["environment"]["record_environment"] = None
        self.assertEqual(pv.assess(f).unmet, ("platform-environment",))
        f = good()
        for k in ("platform",):
            f["record"][k] = f["run_dir"][k] = f["copy"][k] = "linux"
        f["environment"].update(trx_prefix="linux", record_environment="Plan 9", env_file_os="Linux")
        self.assertEqual(pv.assess(f).unmet, ("platform-environment",))

    def test_an_empty_test_name_is_no_test(self):
        f = good()
        f["test"]["name"] = ""
        f["trx"]["tests"] = {"": ["Passed"]}
        self.assertEqual(pv.assess(f).unmet, ("test-executed",))

    def test_platform_environment_details(self):
        f = good()
        f["environment"]["record_environment"] = "Plan 9"
        self.assertEqual(pv.assess(f).unmet, ("platform-environment",))
        f = good()
        for k, v in (("platform", "linux"),):
            f["record"][k] = v
            f["run_dir"][k] = v
            f["copy"][k] = v
        f["environment"].update(trx_prefix="linux", record_environment="WSL Ubuntu · git 2.53.0 (not CI)", env_file_os="Linux")
        self.assertTrue(pv.assess(f).proven)
        f["environment"]["env_file_os"] = None
        self.assertEqual(pv.assess(f).unmet, ("platform-environment",))
        f["environment"]["env_file_os"] = "Windows"
        self.assertEqual(pv.assess(f).unmet, ("platform-environment",))

    def test_test_executed_details(self):
        for guard in ("LISTED", "NOT_LISTED_TRUNCATED_LIST", "", None, "whatever"):
            f = good()
            f["test"]["guard"] = guard
            with self.subTest(guard):
                self.assertEqual(pv.assess(f).unmet, ("test-executed",))
        for outcomes in (["Failed"], ["Passed", "Failed"], ["NotExecuted"], [], ["Warning"]):
            f = good()
            f["trx"]["tests"]["Codelaxy.Tests.A.B"] = outcomes
            with self.subTest(outcomes):
                self.assertEqual(pv.assess(f).unmet, ("test-executed",))
        f = good()
        f["trx"]["tests"] = {}
        self.assertEqual(pv.assess(f).unmet, ("test-executed",))
        f = good()
        f["trx"]["tests"]["Codelaxy.Tests.A.B"] = ["Passed", "Passed"]
        self.assertTrue(pv.assess(f).proven)

    def test_missing_or_malformed_facts_never_prove_anything_and_never_crash(self):
        for bad in (None, [], "x", {}, {"record": None}, {"record": [], "trx": 3, "copy": "x"}):
            a = pv.assess(bad)
            with self.subTest(repr(bad)):
                self.assertFalse(a.proven)
                self.assertEqual(len(a.unmet), 6)
        f = good()
        for k in list(f):
            g = copy.deepcopy(f)
            del g[k]
            with self.subTest(removed=k):
                self.assertFalse(pv.assess(g).proven)

    def test_the_input_is_not_modified_and_the_result_is_deterministic(self):
        f = good()
        before = copy.deepcopy(f)
        a, b = pv.assess(f), pv.assess(f)
        self.assertEqual(f, before)
        self.assertEqual(a, b)

    def test_this_python_parses_a_seven_digit_fraction_without_help(self):
        # documents why provenance._FRACTION is redundant on every Python the suite is run with (the mutant PV29 relies on it)
        from datetime import datetime
        self.assertEqual(datetime.fromisoformat("2026-11-01T16:12:09.0855674+01:00").microsecond, 85567)

    def test_the_names_are_the_catalogue(self):
        self.assertEqual(pv.POINT_NAMES, {1: "run-identity", 2: "head", 3: "manifest-at-run", 4: "platform-environment", 5: "copy-unchanged", 6: "test-executed"})


if __name__ == "__main__":
    unittest.main()
