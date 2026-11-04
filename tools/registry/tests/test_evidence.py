"""IMP2-09 - evidence classes, qualification Q1-Q9, derived verification and the gate (tier A: no false VERIFIED, ever)."""
import copy
import itertools
import unittest

from clxreg import evidence as ev
from clxreg import provenance

H = "227733484a1851bc512f7ba3fef6dd78b6d0e5da"
FP = "c" * 64
REQ = "CLX-REQ-0001"


def evd(**o):
    e = {"lifecycle": "ACTIVE", "scenario": "CLX-SCN-0001", "scenario_revision": 1, "result": "PASS", "performed_at": "2026-11-01T16:12:09",
         "evidences": [{"requirement": REQ, "requirement_revision": 1, "acceptance": "AC-1"}],
         "subject": {"repository": "r", "commit": H, "tree_state": "CLEAN"}, "platform": {"os": "win"},
         "executor": {"kind": "ci", "name": "ci", "independence": "independent"}, "source": {"availability": "AVAILABLE", "integrity": "HASH_CHECKED"},
         "artifacts": [{"role": "trx", "locator": "x.trx", "sha256": "a" * 64}], "observations": [{"name": "T.One", "outcome": "PASS"}]}
    e.update(o)
    return e


def scn(**o):
    s = {"revision": 1, "method": "test", "observation_required": True, "implementation": [{"test": "T.One"}],
         "verifies": [{"requirement": REQ, "acceptance": "AC-1", "adequacy": "ACCEPTED", "basis": "CLX-DEC-0001"}]}
    s.update(o)
    return s


def req(**o):
    r = {"id": REQ, "revision": 1, "definition": "DEFINED", "persistence": "ONCE", "applies_to": {"platforms": ["win"]},
         "acceptance": [{"id": "AC-1", "kind": "evidence", "resolved": True}]}
    r.update(o)
    return r


def proven():
    f = {"record": {"run_id": "3f1ad39e", "stamp": "20261101-160858", "head": H, "platform": "win", "timestamp": "2026-11-01T16:12:09"},
         "run_dir": {"id": "3f1ad39e", "stamp": "20261101-160858", "platform": "win"},
         "trx": {"present": True, "start": "2026-11-01T16:09:37", "finish": "2026-11-01T16:12:09", "tests": {"T.One": ["Passed"]}},
         "copy": {"exists": True, "id": "3f1ad39e", "stamp": "20261101-160858", "platform": "win", "has_git": False, "head": None},
         "manifest_at_run": {"kind": "tree", "digest": "d" * 64, "captured_at": "2026-11-01T16:09:00", "excludes": ["bin", "obj"], "head": H},
         "manifest_now": {"kind": "tree", "digest": "d" * 64, "excludes": ["bin", "obj"]},
         "environment": {"utc_offset": "+01:00", "trx_prefix": "win", "record_environment": "Windows", "env_file_os": None},
         "test": {"name": "T.One", "guard": "NOT_LISTED_COMPLETE_LIST"}}
    a = provenance.assess(f)
    assert a.proven, a.unmet
    return a


def provisional(**o):
    return ev.attach_provenance(evd(subject={"repository": "r", "commit": H, "tree_state": "DIRTY"}, **o), proven(), FP)


def unbound(**o):
    return evd(subject={"repository": "r", "commit": H, "tree_state": "DIRTY"}, **o)


def unlocated(**o):
    return evd(source={"availability": "UNLOCATED", "integrity": "NOT_CHECKED"}, artifacts=[], **o)


def unverified(**o):
    return evd(source={"availability": "AVAILABLE", "integrity": "NOT_CHECKED"}, **o)


MAKERS = {ev.COMMIT_BOUND: evd, ev.PROVISIONAL: provisional, ev.UNBOUND: unbound, ev.UNLOCATED: unlocated, ev.UNVERIFIED_RESULT: unverified}


class ClassifyTests(unittest.TestCase):
    def test_each_class_is_produced_by_its_own_kind_of_evidence(self):
        for cls, make in MAKERS.items():
            with self.subTest(cls):
                self.assertEqual(ev.classify(make()).cls, cls)

    def test_a_clean_tree_needs_a_full_commit_hash(self):
        for c in (H[:7], "", None, H.upper(), "x" * 40):
            with self.subTest(repr(c)):
                self.assertEqual(ev.classify(evd(subject={"commit": c, "tree_state": "CLEAN"})).cls, ev.UNBOUND)
        self.assertEqual(ev.classify(evd(subject={"commit": "a" * 64, "tree_state": "CLEAN"})).cls, ev.COMMIT_BOUND)

    def test_an_unknown_or_missing_tree_state_is_unbound(self):
        for st in ("UNKNOWN", None, "clean", "Dirty"):
            self.assertEqual(ev.classify(evd(subject={"commit": H, "tree_state": st})).cls, ev.UNBOUND, st)

    def test_a_dirty_tree_is_provisional_only_with_a_fingerprint_and_all_six_proven_points(self):
        base = provisional()
        self.assertEqual(ev.classify(base).cls, ev.PROVISIONAL)
        cases = {
            "no fingerprint": lambda e: e["subject"].pop("fingerprint"), "short fingerprint": lambda e: e["subject"].update(fingerprint="abc"),
            "not assessed": lambda e: e["provenance"].update(assessed=False), "no provenance": lambda e: e.pop("provenance"),
            "proven flag without the points": lambda e: e["provenance"].pop("points"), "empty points": lambda e: e["provenance"].update(points=[]),
            "five points only": lambda e: e["provenance"]["points"].pop(), "one point not holding": lambda e: e["provenance"]["points"][2].update(holds=False),
            "one point holds as a string": lambda e: e["provenance"]["points"][0].update(holds="yes"), "a renamed point": lambda e: e["provenance"]["points"][1].update(name="whatever"),
            "proven false": lambda e: e["provenance"].update(proven=False), "short commit": lambda e: e["subject"].update(commit=H[:7]),
        }
        for name, mutate in cases.items():
            e = copy.deepcopy(base)
            mutate(e)
            c = ev.classify(e)
            with self.subTest(name):
                self.assertEqual(c.cls, ev.UNBOUND)
                self.assertTrue(c.reasons)

    def test_unbound_names_the_unmet_points(self):
        a = provenance.assess({})
        e = ev.attach_provenance(unbound(), a, FP)
        c = ev.classify(e)
        self.assertEqual(c.cls, ev.UNBOUND)
        self.assertIn("head", "; ".join(c.reasons))
        self.assertIn("manifest-at-run", "; ".join(c.reasons))

    def test_an_unknown_tree_state_is_unbound_even_with_a_fingerprint_and_proven_provenance(self):
        e = provisional()
        e["subject"]["tree_state"] = "UNKNOWN"
        c = ev.classify(e)
        self.assertEqual(c.cls, ev.UNBOUND)
        self.assertIn("tree state", "; ".join(c.reasons))

    def test_attach_provenance_records_that_the_points_were_not_all_proven(self):
        out = ev.attach_provenance(unbound(), provenance.assess({}), FP)
        self.assertIs(out["provenance"]["proven"], False)
        self.assertEqual(out["provenance"]["unmet"], list(provenance.assess({}).unmet))

    def test_no_artifact_or_unavailable_is_unlocated_whatever_else_is_good(self):
        for o in ({"artifacts": []}, {"artifacts": None}, {"source": {"availability": "LOST", "integrity": "NOT_CHECKED"}}, {"source": {"availability": "UNLOCATED"}}, {"source": {}}):
            with self.subTest(repr(o)):
                self.assertEqual(ev.classify(evd(**o)).cls, ev.UNLOCATED)

    def test_an_artifact_that_exists_but_cannot_be_shown_is_an_unverified_result(self):
        cases = {"integrity": {"source": {"availability": "AVAILABLE", "integrity": "NOT_CHECKED"}}, "no sha": {"artifacts": [{"role": "trx", "locator": "x"}]},
                 "bad sha": {"artifacts": [{"role": "trx", "locator": "x", "sha256": "A" * 64}]}, "no locator": {"artifacts": [{"role": "trx", "sha256": "a" * 64}]},
                 "no platform": {"platform": {}}, "no executor": {"executor": None}, "bad executor kind": {"executor": {"kind": "robot", "independence": "author"}},
                 "bad independence": {"executor": {"kind": "ci", "independence": "trust-me"}}, "bad result": {"result": "GREEN"}, "second artifact bad": {
                     "artifacts": [{"role": "trx", "locator": "x", "sha256": "a" * 64}, {"role": "log", "locator": "y", "sha256": "z"}]}}
        for name, o in cases.items():
            with self.subTest(name):
                self.assertEqual(ev.classify(evd(**o)).cls, ev.UNVERIFIED_RESULT)

    def test_precedence_unlocated_then_unverified_then_binding(self):
        both = evd(artifacts=[], source={"availability": "UNLOCATED", "integrity": "NOT_CHECKED"}, platform={})
        self.assertEqual(ev.classify(both).cls, ev.UNLOCATED)
        self.assertEqual(ev.classify(unverified(subject={"commit": H, "tree_state": "DIRTY"})).cls, ev.UNVERIFIED_RESULT)

    def test_garbage_in_never_raises_and_is_never_a_good_class(self):
        for bad in (None, [], "x", 1, {}, {"source": 3}, {"artifacts": "x", "source": {"availability": "AVAILABLE"}}):
            self.assertIn(ev.classify(bad).cls, (ev.UNVERIFIED_RESULT, ev.UNLOCATED), repr(bad))

    def test_the_class_is_derived_not_stored_and_the_input_is_not_modified(self):
        e = provisional()
        before = copy.deepcopy(e)
        ev.classify(e)
        self.assertEqual(e, before)
        e["evidence_class"] = "COMMIT_BOUND"                       # a stored claim of a class changes nothing
        self.assertEqual(ev.classify(e).cls, ev.PROVISIONAL)

    def test_attach_provenance_records_the_points_and_does_not_touch_the_original(self):
        e = unbound()
        before = copy.deepcopy(e)
        out = ev.attach_provenance(e, proven(), FP)
        self.assertEqual(e, before)
        self.assertEqual(out["subject"]["fingerprint"], FP)
        self.assertEqual([p["n"] for p in out["provenance"]["points"]], [1, 2, 3, 4, 5, 6])
        self.assertTrue(out["provenance"]["proven"])
        self.assertNotIn("evidence_class", out)


class ValidateTests(unittest.TestCase):
    def test_a_good_record_has_no_findings(self):
        self.assertEqual(ev.validate_evd(evd()), [])

    def test_missing_pieces_are_de09(self):
        for f in ("subject", "platform", "executor", "performed_at", "result"):
            e = evd()
            e.pop(f)
            with self.subTest(f):
                self.assertTrue(any(x.code == "DE-09" for x in ev.validate_evd(e)))
        e = evd(subject={"repository": "r", "tree_state": "CLEAN"})
        self.assertTrue(any("commit" in x.message for x in ev.validate_evd(e)))
        self.assertTrue(any(x.code == "DE-09" for x in ev.validate_evd(evd(artifacts=[{"role": "trx", "locator": "x"}]))))
        self.assertTrue(ev.validate_evd(None))


class QualifyTests(unittest.TestCase):
    def ctx(self, **o):
        c = {"requirement": REQ, "revisions": (1,), "acceptance": "AC-1", "platform": "win", "persistence": "ONCE", "freshness": "CURRENT", "required_independence": "none",
             "scenario_revisions": (1,), "newer_fail": False}
        c.update(o)
        return c

    def q(self, e=None, s=None, **o):
        return ev.qualify(e if e is not None else evd(), s if s is not None else scn(), self.ctx(**o))

    def test_the_good_case_qualifies(self):
        r = self.q()
        self.assertEqual((r.qualifies, r.failed, r.cls, r.stale), (True, (), ev.COMMIT_BOUND, False))

    def test_each_condition_alone_makes_it_fail_and_is_named(self):
        cases = {
            "CLASS": dict(e=provisional()), "Q1": dict(e=evd(result="FAIL")), "Q1m": dict(e=evd(), s=scn(method="mutation")),
            "Q2": dict(e=evd(lifecycle="SUPERSEDED")), "Q2n": dict(newer_fail=True),
            "Q3": dict(e=evd(source={"availability": "AVAILABLE", "integrity": "NOT_CHECKED"})),
            "Q4": dict(e=evd(evidences=[{"requirement": REQ, "requirement_revision": 2, "acceptance": "AC-1"}])),
            "Q4b": dict(e=evd(evidences=[{"requirement": REQ, "requirement_revision": 1, "acceptance": "AC-2"}])),
            "Q4c": dict(e=evd(evidences=[{"requirement": "CLX-REQ-0002", "requirement_revision": 1, "acceptance": "AC-1"}])),
            "Q5": dict(s=scn(verifies=[{"requirement": REQ, "acceptance": "AC-1", "adequacy": "ASSERTED", "basis": "CLX-DEC-0001"}])),
            "Q5b": dict(s=scn(verifies=[{"requirement": REQ, "acceptance": "AC-1", "adequacy": "ACCEPTED"}])),
            "Q5c": dict(e=evd(scenario_revision=2)), "Q5d": dict(s=scn(verifies=[])),
            "Q5e": dict(s=scn(verifies=[{"requirement": "CLX-REQ-0002", "acceptance": "AC-1", "adequacy": "ACCEPTED", "basis": "CLX-DEC-0001"}])),
            "Q5f": dict(s=scn(verifies=[{"requirement": REQ, "acceptance": "AC-2", "adequacy": "ACCEPTED", "basis": "CLX-DEC-0001"}])),
            "Q6": dict(e=evd(platform={"os": "linux"})),
            "Q7": dict(required_independence="independent", e=evd(executor={"kind": "agent", "name": "a", "independence": "author"})),
            "Q7s": dict(s=scn(independence_required="owner")),
            "Q8": dict(persistence="CONTINUOUS", freshness="STALE"), "Q8u": dict(persistence="UNSPECIFIED", freshness="UNDETERMINED"), "Q8n": dict(persistence="CONTINUOUS", freshness=None),
            "Q8p": dict(persistence=None, freshness="STALE"),
            "Q9": dict(e=evd(observations=[])), "Q9b": dict(e=evd(observations=[{"name": "T.One", "outcome": "UNVERIFIED"}])),
            "Q9c": dict(e=evd(observations=[{"name": "T.One", "outcome": "ABSENT"}])), "Q9d": dict(e=evd(observations=[{"name": "T.One", "outcome": "SKIP"}])),
            "Q9e": dict(s=scn(implementation=[])),
            "Q9f": dict(e=evd(observations=[]), s=scn(observation_required=False)),
            "Q9g": dict(e=evd(observations=[], baseline="CLX-EVD-0001"), s=scn(method="mutation", observation_required=False)),
        }
        for name, o in cases.items():
            e, s = o.pop("e", None), o.pop("s", None)
            r = self.q(e, s, **o)
            with self.subTest(name):
                self.assertFalse(r.qualifies)
                codes = [f.split(":")[0] for f in r.failed]
                want = ["CLASS", "Q3"] if name == "Q3" else ["CLASS"] if name == "CLASS" else [name[:2]]       # an unchecked source is both a class and a Q3 failure
                self.assertEqual(codes, want, r.failed)

    def test_independence_is_ordered(self):
        for have, need, ok in (("author", "none", True), ("author", "independent", False), ("independent", "independent", True), ("independent", "owner", False), ("owner", "independent", True)):
            e = evd(executor={"kind": "human", "name": "n", "independence": have})
            self.assertEqual(self.q(e, required_independence=need).qualifies, ok, (have, need))

    def test_a_mutation_with_a_baseline_and_observation_qualifies(self):
        s = scn(method="mutation")
        self.assertTrue(self.q(evd(baseline="CLX-EVD-0001"), s).qualifies)

    def test_a_scenario_that_is_not_a_test_needs_no_observation_unless_it_says_so(self):
        s = scn(method="inspection", observation_required=False, implementation=[])
        self.assertTrue(self.q(evd(observations=[]), s).qualifies)

    def test_every_implementing_test_must_have_a_pass_observation(self):
        s = scn(implementation=[{"test": "T.One"}, {"test": "T.Two"}])
        self.assertFalse(self.q(evd(), s).qualifies)
        self.assertTrue(self.q(evd(observations=[{"name": "T.One", "outcome": "PASS"}, {"name": "T.Two", "outcome": "PASS"}]), s).qualifies)

    def test_a_stale_evidence_is_stale_only_when_nothing_else_is_wrong(self):
        r = self.q(persistence="CONTINUOUS", freshness="STALE")
        self.assertEqual((r.qualifies, r.stale), (False, True))
        self.assertFalse(self.q(evd(result="FAIL"), persistence="CONTINUOUS", freshness="STALE").stale)
        self.assertFalse(self.q(provisional(), persistence="CONTINUOUS", freshness="STALE").stale)
        self.assertFalse(self.q(persistence="CONTINUOUS", freshness="UNDETERMINED").stale)

    def test_a_once_requirement_does_not_need_freshness(self):
        self.assertTrue(self.q(persistence="ONCE", freshness=None).qualifies)

    def test_editorial_revisions_count_as_the_same_condition(self):
        e = evd(evidences=[{"requirement": REQ, "requirement_revision": 1, "acceptance": "AC-1"}])
        self.assertTrue(self.q(e, revisions=(1, 2)).qualifies)
        self.assertFalse(self.q(e, revisions=(2,)).qualifies)

    def test_garbage_does_not_raise_and_does_not_qualify(self):
        for e, s in ((None, None), ([], {}), ({}, []), ("x", "y")):
            r = ev.qualify(e, s, self.ctx())
            self.assertFalse(r.qualifies)


class DeriveTests(unittest.TestCase):
    def d(self, r=None, scns=None, evds=None, env=None):
        return ev.derive(r or req(), scns if scns is not None else {"CLX-SCN-0001": scn()}, evds if evds is not None else {"CLX-EVD-0001": evd()}, env)

    def test_one_good_evidence_verifies(self):
        d = self.d()
        self.assertEqual((d.verification, d.effective_status, d.conditions), ("VERIFIED", "DONE", {"AC-1": "SATISFIED"}))

    def test_no_evidence_is_unverified_and_says_why(self):
        d = self.d(evds={})
        self.assertEqual((d.verification, d.effective_status), ("UNVERIFIED", "UNVERIFIED"))
        self.assertTrue(d.findings)

    def test_the_matrix_of_classes_freshness_platform_adequacy_and_result(self):
        for cls, fresh, plat, adq, res in itertools.product(MAKERS, ("CURRENT", "STALE"), ("win", "linux"), ("ACCEPTED", "ASSERTED"), ("PASS", "FAIL")):
            e = MAKERS[cls](result=res, platform={"os": plat})
            s = scn(verifies=[{"requirement": REQ, "acceptance": "AC-1", "adequacy": adq, "basis": "CLX-DEC-0001"}])
            r = req(persistence="CONTINUOUS")
            d = self.d(r, {"CLX-SCN-0001": s}, {"CLX-EVD-0001": e}, {"freshness": {"CLX-EVD-0001": fresh}})
            if plat != "win":
                want = "UNVERIFIED"                                           # evidence of another platform says nothing about win
            elif res == "FAIL":
                want = "FAILED"                                               # a recorded failure blocks whatever its class
            elif cls == ev.COMMIT_BOUND and adq == "ACCEPTED":
                want = "VERIFIED" if fresh == "CURRENT" else "STALE"
            else:
                want = "UNVERIFIED"
            with self.subTest(cls=cls, fresh=fresh, platform=plat, adequacy=adq, result=res):
                self.assertEqual(d.verification, want)
                if cls != ev.COMMIT_BOUND:
                    self.assertNotEqual(d.verification, "VERIFIED")

    def test_provisional_evidence_changes_nothing_but_is_listed(self):
        e = provisional()
        d = self.d(evds={"CLX-EVD-0001": e})
        self.assertEqual((d.verification, d.effective_status), ("UNVERIFIED", "UNVERIFIED"))
        self.assertEqual([(p[0], p[1], p[2], p[3]) for p in d.provisional], [("CLX-EVD-0001", "AC-1", "win", FP)])
        base = self.d(evds={})
        self.assertEqual((d.verification, d.effective_status, d.conditions), (base.verification, base.effective_status, base.conditions))

    def test_provisional_next_to_a_commit_bound_evidence_does_not_change_the_state_either(self):
        both = self.d(evds={"CLX-EVD-0001": evd(), "CLX-EVD-0002": provisional()})
        alone = self.d(evds={"CLX-EVD-0001": evd()})
        self.assertEqual((both.verification, both.conditions), (alone.verification, alone.conditions))

    def test_unlocated_unbound_and_unverified_evidence_leave_named_findings(self):
        codes = {}
        for cls in (ev.UNLOCATED, ev.UNBOUND, ev.UNVERIFIED_RESULT):
            d = self.d(evds={"CLX-EVD-0001": MAKERS[cls]()})
            codes[cls] = {f.code for f in d.findings}
            self.assertEqual(d.verification, "UNVERIFIED")
        self.assertIn("EM-04", codes[ev.UNLOCATED])
        self.assertIn("EM-12", codes[ev.UNBOUND])
        self.assertIn("EM-04", codes[ev.UNVERIFIED_RESULT])

    def test_an_unresolved_requirement_is_unknown_even_with_perfect_evidence(self):
        d = self.d(req(definition="UNRESOLVED"))
        self.assertEqual((d.verification, d.effective_status), ("UNKNOWN", "UNKNOWN"))
        self.assertIn("EM-01", {f.code for f in d.findings})

    def test_an_unresolved_condition_makes_the_requirement_unknown(self):
        r = req(acceptance=[{"id": "AC-1", "kind": "evidence", "resolved": False}])
        self.assertEqual(self.d(r).verification, "UNKNOWN")

    def test_a_requirement_without_evidence_conditions_is_unverified(self):
        self.assertEqual(self.d(req(acceptance=[])).verification, "UNVERIFIED")
        self.assertEqual(self.d(req(acceptance=[{"id": "AC-1", "kind": "decision", "resolved": True}])).verification, "UNVERIFIED")

    def test_two_platforms_need_two_qualifying_evidences(self):
        r = req(applies_to={"platforms": ["win", "linux"]})
        w, l = evd(), evd(platform={"os": "linux"})
        self.assertEqual(self.d(r, evds={"CLX-EVD-0001": w}).verification, "PARTIALLY_VERIFIED")
        self.assertEqual(self.d(r, evds={"CLX-EVD-0001": w}).effective_status, "PARTIAL")
        self.assertEqual(self.d(r, evds={"CLX-EVD-0001": w, "CLX-EVD-0002": l}).verification, "VERIFIED")
        self.assertIn("EM-08", {f.code for f in self.d(r, evds={"CLX-EVD-0001": w}).findings})

    def test_a_condition_may_name_its_own_platforms(self):
        r = req(acceptance=[{"id": "AC-1", "kind": "evidence", "resolved": True, "requires": {"platforms": ["linux"]}}])
        self.assertEqual(self.d(r, evds={"CLX-EVD-0001": evd()}).verification, "UNVERIFIED")
        self.assertEqual(self.d(r, evds={"CLX-EVD-0001": evd(platform={"os": "linux"})}).verification, "VERIFIED")

    def test_two_conditions_one_satisfied_is_partial(self):
        r = req(acceptance=[{"id": "AC-1", "kind": "evidence", "resolved": True}, {"id": "AC-2", "kind": "evidence", "resolved": True}])
        self.assertEqual(self.d(r).verification, "PARTIALLY_VERIFIED")

    def test_a_failure_wins_over_a_pass_unless_it_was_superseded(self):
        evds = {"CLX-EVD-0001": evd(), "CLX-EVD-0002": evd(result="FAIL")}
        self.assertEqual(self.d(evds=evds).verification, "FAILED")
        evds["CLX-EVD-0002"]["lifecycle"] = "SUPERSEDED"
        self.assertEqual(self.d(evds=evds).verification, "VERIFIED")

    def test_an_active_failure_blocks_even_when_another_record_names_it_as_superseded_by_a_failure(self):
        # only the failure's own lifecycle lifts it; a later failure record that is itself not active lifts nothing
        evds = {"CLX-EVD-0001": evd(), "CLX-EVD-0002": evd(result="FAIL"), "CLX-EVD-0003": evd(result="FAIL", lifecycle="SUPERSEDED", supersedes=["CLX-EVD-0002"])}
        self.assertEqual(self.d(evds=evds).verification, "FAILED")

    def test_a_newer_failure_withdraws_an_older_pass(self):
        evds = {"CLX-EVD-0001": evd(), "CLX-EVD-0002": evd(result="FAIL", supersedes=["CLX-EVD-0001"])}
        self.assertEqual(self.d(evds=evds).verification, "FAILED")

    def test_staleness_comes_from_the_environment_and_is_not_verified(self):
        r = req(persistence="CONTINUOUS")
        self.assertEqual(self.d(r, env={"freshness": {"CLX-EVD-0001": "CURRENT"}}).verification, "VERIFIED")
        d = self.d(r, env={"freshness": {"CLX-EVD-0001": "STALE"}})
        self.assertEqual((d.verification, d.effective_status), ("STALE", "UNVERIFIED"))
        self.assertEqual(self.d(r).verification, "UNVERIFIED")                 # freshness not assessed at all: not current

    def test_equivalent_revisions_are_taken_from_the_environment(self):
        e = evd(evidences=[{"requirement": REQ, "requirement_revision": 1, "acceptance": "AC-1"}])
        r = req(revision=2)
        self.assertEqual(self.d(r, evds={"CLX-EVD-0001": e}).verification, "UNVERIFIED")
        self.assertEqual(self.d(r, evds={"CLX-EVD-0001": e}, env={"equivalent_revisions": {REQ: (1, 2)}}).verification, "VERIFIED")

    def test_inputs_are_not_modified(self):
        r, s, e = req(), {"CLX-SCN-0001": scn()}, {"CLX-EVD-0001": provisional()}
        before = copy.deepcopy((r, s, e))
        self.d(r, s, e)
        self.assertEqual((r, s, e), before)


class GateTests(unittest.TestCase):
    def test_a_gate_with_a_single_provisional_evidence_fails(self):
        g = ev.gate([req()], {"CLX-SCN-0001": scn()}, {"CLX-EVD-0001": provisional()})
        self.assertFalse(g["passed"])
        self.assertEqual(g["failing"], [{"requirement": REQ, "verification": "UNVERIFIED"}])
        self.assertEqual([p[:3] for p in g["provisional"]], [(REQ, "CLX-EVD-0001", "AC-1")])

    def test_a_gate_passes_only_when_every_requirement_is_verified(self):
        r2 = req(id="CLX-REQ-0002")
        e2 = evd(evidences=[{"requirement": "CLX-REQ-0002", "requirement_revision": 1, "acceptance": "AC-1"}])
        s = {"CLX-SCN-0001": scn(), "CLX-SCN-0002": scn(verifies=[{"requirement": "CLX-REQ-0002", "acceptance": "AC-1", "adequacy": "ACCEPTED", "basis": "CLX-DEC-0001"}])}
        s["CLX-SCN-0002"]["id"] = "CLX-SCN-0002"
        e2["scenario"] = "CLX-SCN-0002"
        self.assertTrue(ev.gate([req(), r2], s, {"CLX-EVD-0001": evd(), "CLX-EVD-0002": e2})["passed"])
        g = ev.gate([req(), r2], s, {"CLX-EVD-0001": evd()})
        self.assertFalse(g["passed"])
        self.assertEqual([f["requirement"] for f in g["failing"]], ["CLX-REQ-0002"])

    def test_a_partially_verified_requirement_does_not_pass_the_gate(self):
        r = req(applies_to={"platforms": ["win", "linux"]})
        g = ev.gate([r], {"CLX-SCN-0001": scn()}, {"CLX-EVD-0001": evd()})
        self.assertFalse(g["passed"])
        self.assertEqual(g["failing"], [{"requirement": REQ, "verification": "PARTIALLY_VERIFIED"}])

    def test_an_empty_gate_does_not_pass(self):
        self.assertFalse(ev.gate([], {}, {})["passed"])

    def test_the_report_shows_provisional_evidence_and_keeps_the_state(self):
        lines = ev.report_lines(req(), {"CLX-SCN-0001": scn()}, {"CLX-EVD-0001": provisional()})
        text = "\n".join(lines)
        self.assertIn("verification UNVERIFIED", text)
        self.assertIn("provisionally supported (not counted): CLX-EVD-0001", text)
        self.assertIn(FP[:12], text)
        done = "\n".join(ev.report_lines(req(), {"CLX-SCN-0001": scn()}, {"CLX-EVD-0001": evd()}))
        self.assertIn("verification VERIFIED, effective DONE", done)
        self.assertNotIn("provisionally", done)


if __name__ == "__main__":
    unittest.main()
