"""IMP2-03 - namespaces and aliases: identity stays separate from historical labels (tier A: this is what keeps RT1-RT3 honest)."""
import copy
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from clxreg import aliases, canon, namespaces, sources, store
from clxreg.findings import ADVISORY, blocking
from tests.test_store import commit_all, git, new_root, put, rec

DOC_V1 = ("Naming: RT1–RT3 are the resolver test gaps.\n"
          "Risk R1 is high. T3b is a mutant. RT10 is something else.\n"
          "A broken range RT1…RT3 and RT4.\n"
          "Another range RT3–RT10 with RT4 inside.\n").encode("utf-8")
DOC_V0 = "Revision 1: R1–R3 are the resolver test gaps.\nR1 killed.\n".encode("utf-8")
FILES = {"doc-v1.md": DOC_V1, "doc-v0.md": DOC_V0}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def srcver(vid, name, status="DRAFT"):
    d = FILES[name]
    return {"id": vid, "sha256": sha(d), "bytes": len(d), "pinning": "sha256-only", "status": status, "location": {"root": "ws", "path": name}}


def src_catalog():
    return {"schema": sources.SCHEMA, "sources": [
        {"key": "doc", "title": "Doc", "category": "DRAFT", "versions": [srcver("v1", "doc-v1.md"), srcver("v0", "doc-v0.md", "HISTORICAL")]}]}


def ns(key, pattern, maps_to="REQ", status="LIVE", ver="v1", **extra):
    d = {"key": key, "label_pattern": pattern, "meaning": key, "authority": {"source": "doc", "version": ver}, "status": status,
         "maps_to": maps_to, "distinct_from": []}
    d.update(extra)
    return d


def ns_catalog():
    return {"schema": namespaces.SCHEMA, "namespaces": [
        ns("micromap-resolver-gaps", "RT[0-9]+"),
        ns("plan-resolver-gaps-v1", "R[0-9]+", status="FROZEN", ver="v0", distinct_from=["risk-classes"]),
        ns("risk-classes", "R[0-4]", maps_to="EXTERNAL"),
        ns("audit-c-mutants", "T[0-9]+b?", maps_to="SCN"),
    ]}


def src_ref(version="v1", **extra):
    d = {"source": "doc", "version": version}
    d.update(extra)
    return d


def al(namespace, value, status="ACTIVE", source=None, **extra):
    d = {"namespace": namespace, "value": value, "status": status, "source": source or src_ref()}
    d.update(extra)
    return d


def recs(**by_id):
    """recs(**{'CLX-REQ-0001': [alias, ...]}) -> {id: record object}"""
    return {rid: {"schema_version": 1, "id": rid, "type": rid.split("-")[1], "title": "t", "aliases": a} for rid, a in by_id.items()}


def R(n, aliases_, typ="REQ"):
    return f"CLX-{typ}-{n:04d}", aliases_


def many(*pairs):
    return recs(**dict(pairs))


def codes(findings):
    return sorted((f.code, f.record) for f in findings)


def only(findings):
    return sorted({f.code for f in findings})


class Fx(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.ws = Path(self._t.name) / "ws"
        self.ws.mkdir()
        for name, data in FILES.items():
            (self.ws / name).write_bytes(data)
        self.roots = {"ws": str(self.ws)}
        self.src = src_catalog()
        self.ns = ns_catalog()

    def check(self, records):
        return aliases.check_aliases(records, self.ns, self.src, self.roots)


class NamespaceCatalogTests(Fx):
    def test_good_catalog(self):
        self.assertEqual(namespaces.validate_namespaces(self.ns, self.src), [])

    def test_works_without_a_source_catalog_but_then_cannot_resolve_authorities(self):
        self.assertEqual(namespaces.validate_namespaces(self.ns), [])

    def test_top_level(self):
        for bad in ([], None, {"schema": namespaces.SCHEMA}, {"namespaces": []}, {"schema": "x", "namespaces": []},
                    {"schema": namespaces.SCHEMA, "namespaces": {}}, {"schema": namespaces.SCHEMA, "namespaces": [], "x": 1}):
            with self.subTest(repr(bad)):
                self.assertEqual(only(namespaces.validate_namespaces(bad)), ["DE-02"])

    def test_namespace_fields(self):
        bad = {
            "no key": lambda n: n.pop("key"), "key upper": lambda n: n.update(key="Risk"), "key space": lambda n: n.update(key="a b"),
            "no pattern": lambda n: n.pop("label_pattern"), "pattern not str": lambda n: n.update(label_pattern=1),
            "pattern invalid regex": lambda n: n.update(label_pattern="R[0-"), "pattern matches empty": lambda n: n.update(label_pattern="R*"),
            "pattern empty": lambda n: n.update(label_pattern=""), "no meaning": lambda n: n.pop("meaning"),
            "meaning empty": lambda n: n.update(meaning=""), "no authority": lambda n: n.pop("authority"),
            "authority not obj": lambda n: n.update(authority="doc"), "authority extra": lambda n: n["authority"].update(x="y"),
            "authority no version": lambda n: n["authority"].pop("version"),
            "bad status": lambda n: n.update(status="DEAD"), "no status": lambda n: n.pop("status"),
            "bad maps_to": lambda n: n.update(maps_to="ADR"), "no maps_to": lambda n: n.pop("maps_to"),
            "distinct not list": lambda n: n.update(distinct_from="risk-classes"), "distinct has non-str": lambda n: n.update(distinct_from=[1]),
            "distinct self": lambda n: n.update(distinct_from=["micromap-resolver-gaps"]), "unknown field": lambda n: n.update(x=1),
            "supersedes not str": lambda n: n.update(supersedes=1), "supersedes itself": lambda n: n.update(supersedes="micromap-resolver-gaps"),
            "authority version not str": lambda n: n["authority"].update(version=1), "authority quote empty": lambda n: n["authority"].update(quote=""),
            "note not str": lambda n: n.update(note=1), "no distinct_from": lambda n: n.pop("distinct_from"),
        }
        for name, mutate in bad.items():
            c = copy.deepcopy(self.ns)
            mutate(c["namespaces"][0])
            with self.subTest(name):
                self.assertIn("DE-02", only(namespaces.validate_namespaces(c, self.src)))

    def test_decision_maps_to_is_allowed(self):
        c = copy.deepcopy(self.ns)
        c["namespaces"][0]["maps_to"] = "DEC"
        self.assertEqual(namespaces.validate_namespaces(c, self.src), [])

    def test_duplicate_key(self):
        c = copy.deepcopy(self.ns)
        c["namespaces"].append(copy.deepcopy(c["namespaces"][0]))
        self.assertIn("DE-01", only(namespaces.validate_namespaces(c)))

    def test_unknown_references_are_de03(self):
        for mutate in (lambda n: n.update(distinct_from=["nope"]), lambda n: n.update(supersedes="nope"),
                       lambda n: n["authority"].update(source="nope"), lambda n: n["authority"].update(version="nope")):
            c = copy.deepcopy(self.ns)
            mutate(c["namespaces"][0])
            with self.subTest():
                self.assertEqual(only(namespaces.validate_namespaces(c, self.src)), ["DE-03"])

    def test_supersedes_must_point_to_an_existing_namespace(self):
        c = copy.deepcopy(self.ns)
        c["namespaces"][0]["supersedes"] = "plan-resolver-gaps-v1"
        self.assertEqual(namespaces.validate_namespaces(c, self.src), [])

    def test_authority_quote_is_checked_against_the_pinned_source(self):
        c = copy.deepcopy(self.ns)
        c["namespaces"][0]["authority"]["quote"] = "RT1–RT3 are the resolver test gaps."
        self.assertEqual(namespaces.check_authorities(c, self.src, self.roots), [])
        c["namespaces"][0]["authority"]["quote"] = "RT1-RT3 are the resolver test gaps."
        self.assertEqual(codes(namespaces.check_authorities(c, self.src, self.roots)), [("DE-13", "sources:doc/v1")])

    def test_authority_quote_with_the_source_missing_from_disk_is_only_advisory(self):
        c = copy.deepcopy(self.ns)
        c["namespaces"][0]["authority"]["quote"] = "anything"
        f = namespaces.check_authorities(c, self.src, {})
        self.assertEqual({x.cls for x in f}, {ADVISORY})

    def test_load(self):
        p = Path(self._t.name) / "ns.json"
        canon.write_record(p, self.ns)
        self.assertEqual(namespaces.load_namespaces(p), (self.ns, []))
        p.write_text(canon.dumps(self.ns).replace("  ", "    "), encoding="utf-8")
        obj, f = namespaces.load_namespaces(p)
        self.assertEqual((obj, only(f)), (self.ns, ["DE-02"]))
        p.write_bytes(b"{nope")
        obj, f = namespaces.load_namespaces(p)
        self.assertEqual((obj, only(f), f[0].record), (None, ["DE-02"], "namespaces"))
        with self.assertRaises(sources.SourceError):
            namespaces.load_namespaces(Path(self._t.name) / "absent.json")

    def test_sorted_and_deterministic(self):
        c = copy.deepcopy(self.ns)
        c["namespaces"][3]["status"] = "x"
        c["namespaces"][0]["maps_to"] = "x"
        f = namespaces.validate_namespaces(c, self.src)
        self.assertEqual([x.record for x in f], sorted(x.record for x in f))
        self.assertEqual([x.line() for x in f], [x.line() for x in namespaces.validate_namespaces(copy.deepcopy(c), self.src)])


class AliasTests(Fx):
    def test_the_rt1_rt3_case(self):
        ok = many(R(1, [al("micromap-resolver-gaps", "RT1")]), R(3, [al("micromap-resolver-gaps", "RT3")]),
                  R(2, [al("micromap-resolver-gaps", "RT2", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT1–RT3"))]))
        self.assertEqual(self.check(ok), [])

    def test_rt2_cannot_be_active_it_does_not_occur_literally(self):
        f = self.check(many(R(2, [al("micromap-resolver-gaps", "RT2")])))
        self.assertEqual(codes(f), [("DE-13", "CLX-REQ-0002")])
        self.assertIn("literally", f[0].message)

    def test_rt2_cannot_be_historical_either(self):
        self.assertEqual(only(self.check(many(R(2, [al("micromap-resolver-gaps", "RT2", "HISTORICAL")])))), ["DE-13"])

    def test_a_label_inside_a_longer_one_is_not_evidence(self):
        # RT10 occurs in the source, RT1 is only a literal because of the range; "RT10" is evidenced, "RT1" at the same time too: check boundaries
        self.assertEqual(self.check(many(R(10, [al("micromap-resolver-gaps", "RT10")]))), [])
        self.assertEqual(only(self.check(many(R(5, [al("micromap-resolver-gaps", "RT5")])))), ["DE-13"])

    def test_implied_by_range_needs_a_range_source(self):
        f = self.check(many(R(2, [al("micromap-resolver-gaps", "RT2", "IMPLIED_BY_RANGE")])))
        self.assertEqual(codes(f), [("DE-12", "CLX-REQ-0002")])

    def test_range_source_only_with_implied_by_range(self):
        for st in ("ACTIVE", "HISTORICAL", "REJECTED", "AMBIGUOUS"):
            f = self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", st, range_source=src_ref(quote="RT1–RT3"))])))
            with self.subTest(st):
                self.assertIn(("DE-12", "CLX-REQ-0001"), codes(f))

    def test_implied_by_range_conditions(self):
        rs = lambda q: dict(range_source=src_ref(quote=q))      # noqa: E731
        cases = {
            "range text not in the source": ("RT2", rs("RT1–RT5")),
            "range with another dash": ("RT2", rs("RT1-RT3")),
            "range not parseable": ("RT2", rs("RT1…RT3")),
            "label is an end of the range": ("RT3", rs("RT1–RT3")),
            "label outside the range": ("RT4", rs("RT1–RT3")),
            "label outside the range, not literal either": ("RT9", rs("RT1–RT3")),
            "label occurs literally": ("RT1", rs("RT1–RT3")),
        }
        for name, (value, extra) in cases.items():
            f = self.check(many(R(2, [al("micromap-resolver-gaps", value, "IMPLIED_BY_RANGE", **extra)])))
            with self.subTest(name):
                self.assertEqual(only(f), ["DE-13"], [x.line() for x in f])

    def test_a_label_inside_a_range_that_also_occurs_literally_is_not_implied(self):
        f = self.check(many(R(4, [al("micromap-resolver-gaps", "RT4", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT3–RT10"))])))
        self.assertEqual(codes(f), [("DE-13", "CLX-REQ-0004")])
        self.assertIn("occurs literally", f[0].message)

    def test_each_failing_range_condition_reports_its_own_reason(self):
        f = self.check(many(R(2, [al("micromap-resolver-gaps", "RT2", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT1…RT3"))])))
        self.assertEqual(len(f), 1)
        self.assertIn("supported range", f[0].message)
        f = self.check(many(R(9, [al("micromap-resolver-gaps", "RT9", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT1–RT3"))])))
        self.assertEqual(len(f), 1)
        self.assertIn("strictly between", f[0].message)

    def test_a_range_that_is_not_in_the_source_is_the_only_finding(self):
        f = self.check(many(R(4, [al("micromap-resolver-gaps", "RT4", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT1–RT5"))])))
        self.assertEqual(len(f), 1)
        self.assertIn("literal substring", f[0].message)

    def test_implied_by_range_with_the_source_not_available_is_advisory(self):
        a = al("micromap-resolver-gaps", "RT2", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT1–RT3"))
        f = aliases.check_aliases(many(R(2, [a])), self.ns, self.src, {})
        self.assertFalse(blocking(f))
        self.assertEqual(len(f), 1)

    def test_range_source_shape(self):
        for bad in ("RT1–RT3", {"source": "doc", "version": "v1"}, {"source": "doc", "version": "v1", "quote": ""},
                    {"source": "doc", "version": "v1", "quote": "RT1–RT3", "x": 1}):
            f = self.check(many(R(2, [al("micromap-resolver-gaps", "RT2", "IMPLIED_BY_RANGE", range_source=bad)])))
            with self.subTest(repr(bad)):
                self.assertIn("DE-02", only(f))

    def test_alias_shape(self):
        base = al("micromap-resolver-gaps", "RT1")
        bad = {
            "no namespace": lambda a: a.pop("namespace"), "no source": lambda a: a.pop("source"), "no value": lambda a: a.pop("value"),
            "no status": lambda a: a.pop("status"), "bad status": lambda a: a.update(status="LIVE"), "lowercase status": lambda a: a.update(status="active"),
            "value int": lambda a: a.update(value=1), "namespace int": lambda a: a.update(namespace=1), "unknown field": lambda a: a.update(x=1),
            "source str": lambda a: a.update(source="doc"), "source no version": lambda a: a.update(source={"source": "doc"}),
            "source extra": lambda a: a["source"].update(x="y"), "source value int": lambda a: a["source"].update(version=1),
            "source value empty": lambda a: a["source"].update(version=""), "note not str": lambda a: a.update(note=1),
        }
        for name, mutate in bad.items():
            a = copy.deepcopy(base)
            mutate(a)
            with self.subTest(name):
                self.assertIn("DE-02", only(self.check(many(R(1, [a])))))

    def test_aliases_must_be_a_list_of_objects(self):
        for bad in ("RT1", {"a": 1}, [1], [None]):
            r = many(R(1, []))
            r["CLX-REQ-0001"]["aliases"] = bad
            with self.subTest(repr(bad)):
                self.assertEqual(only(self.check(r)), ["DE-02"])

    def test_records_without_aliases_are_fine(self):
        r = many(R(1, []))
        del r["CLX-REQ-0001"]["aliases"]
        self.assertEqual(self.check(r), [])

    def test_optional_note_and_source_anchor(self):
        a = al("micromap-resolver-gaps", "RT1", note="n", source=src_ref(anchor="Naming", fragment="x"))
        self.assertEqual(self.check(many(R(1, [a]))), [])

    def test_unknown_namespace_and_pattern_mismatch_are_de05(self):
        self.assertEqual(only(self.check(many(R(1, [al("nope", "RT1")])))), ["DE-05"])
        for v in ("RTx", "rt1", "RT1 ", " RT1", "XRT1", "RT", "RT1\n", "RT١"):
            with self.subTest(repr(v)):
                self.assertEqual(only(self.check(many(R(1, [al("micromap-resolver-gaps", v)])))), ["DE-05"])

    def test_same_namespace_and_value_on_two_records_is_de05_on_both(self):
        f = self.check(many(R(1, [al("micromap-resolver-gaps", "RT1")]), R(2, [al("micromap-resolver-gaps", "RT1")])))
        self.assertEqual(codes(f), [("DE-05", "CLX-REQ-0001"), ("DE-05", "CLX-REQ-0002")])

    def test_twice_on_one_record_is_also_a_duplicate(self):
        f = self.check(many(R(1, [al("micromap-resolver-gaps", "RT1"), al("micromap-resolver-gaps", "RT1", "HISTORICAL")])))
        self.assertIn("DE-05", only(f))

    def test_the_same_string_in_several_namespaces_is_not_a_conflict(self):
        r = many(R(1, [al("plan-resolver-gaps-v1", "R1", "HISTORICAL", source=src_ref("v0"))]), R(2, [al("risk-classes", "R1")]))
        self.assertEqual(self.check(r), [])

    def test_ad01_the_same_value_in_two_namespaces_without_distinct_from(self):
        c = copy.deepcopy(self.ns)
        c["namespaces"][1]["distinct_from"] = []
        r = many(R(1, [al("plan-resolver-gaps-v1", "R1", "HISTORICAL", source=src_ref("v0"))]), R(2, [al("risk-classes", "R1")]))
        f = aliases.check_aliases(r, c, self.src, self.roots)
        self.assertEqual([(x.cls, x.code) for x in f], [(ADVISORY, "AD-01")])
        c["namespaces"][2]["distinct_from"] = ["plan-resolver-gaps-v1"]                      # declared from either side
        self.assertEqual(aliases.check_aliases(r, c, self.src, self.roots), [])

    def test_an_unknown_namespace_sharing_a_string_with_a_known_one_is_only_de05(self):
        r = many(R(1, [al("nope", "R1")]), R(2, [al("risk-classes", "R1")]))
        self.assertEqual(codes(self.check(r)), [("DE-05", "CLX-REQ-0001")])

    def test_source_references_are_resolved(self):
        self.assertEqual(only(self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", source=src_ref("nope"))])))), ["DE-03"])
        self.assertEqual(only(self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", source={"source": "nope", "version": "v1"})])))), ["DE-03"])

    def test_source_missing_on_disk_skips_the_literal_check_with_ad04(self):
        f = aliases.check_aliases(many(R(2, [al("micromap-resolver-gaps", "RT2")])), self.ns, self.src, {})
        self.assertEqual({(x.cls, x.code) for x in f}, {(ADVISORY, "AD-04")})

    def test_changed_source_makes_the_evidence_untrusted(self):
        (self.ws / "doc-v1.md").write_bytes(DOC_V1 + b" RT2\n")
        f = self.check(many(R(2, [al("micromap-resolver-gaps", "RT2")])))
        self.assertEqual(only(f), ["DE-13"])
        self.assertIn("differs from the pinned", f[0].message)

    def test_quote_in_an_alias_source_is_checked(self):
        good = al("micromap-resolver-gaps", "RT1", source=src_ref(quote="RT1–RT3 are the resolver test gaps."))
        bad = al("micromap-resolver-gaps", "RT1", source=src_ref(quote="RT1 are the resolver test gaps."))
        self.assertEqual(self.check(many(R(1, [good]))), [])
        self.assertEqual(only(self.check(many(R(1, [bad])))), ["DE-13"])

    def test_rejected_alias_needs_a_resolvable_source_but_no_literal_occurrence(self):
        self.assertEqual(self.check(many(R(1, [al("audit-c-mutants", "T3b", "REJECTED")]))), [])
        self.assertEqual(self.check(many(R(1, [al("audit-c-mutants", "T9", "REJECTED")]))), [])
        self.assertEqual(only(self.check(many(R(1, [al("audit-c-mutants", "T9", "REJECTED", source=src_ref("nope"))])))), ["DE-03"])

    def test_historical_alias_with_literal_evidence(self):
        self.assertEqual(self.check(many(R(1, [al("plan-resolver-gaps-v1", "R1", "HISTORICAL", source=src_ref("v0"))]))), [])
        self.assertEqual(only(self.check(many(R(1, [al("plan-resolver-gaps-v1", "R2", "HISTORICAL", source=src_ref("v0"))])))), ["DE-13"])    # R2 is only in a range

    def test_ambiguous_aliases_must_name_each_other(self):
        a = lambda other: al("micromap-resolver-gaps", "RT1", "AMBIGUOUS", ambiguous_with=other)           # noqa: E731
        ok = many(R(1, [a(["CLX-REQ-0002"])]), R(2, [a(["CLX-REQ-0001"])]))
        self.assertEqual(self.check(ok), [])
        for name, r in {
            "one side missing": many(R(1, [a(["CLX-REQ-0002"])]), R(2, [a([])])),
            "no field": many(R(1, [al("micromap-resolver-gaps", "RT1", "AMBIGUOUS")]), R(2, [al("micromap-resolver-gaps", "RT1", "AMBIGUOUS")])),
            "wrong target": many(R(1, [a(["CLX-REQ-0003"])]), R(2, [a(["CLX-REQ-0001"])])),
            "lists itself": many(R(1, [a(["CLX-REQ-0001", "CLX-REQ-0002"])]), R(2, [a(["CLX-REQ-0001"])])),
            "mixed with active": many(R(1, [a(["CLX-REQ-0002"])]), R(2, [al("micromap-resolver-gaps", "RT1")])),
        }.items():
            with self.subTest(name):
                self.assertIn("DE-05", only(self.check(r)))

    def test_ambiguous_with_only_on_ambiguous_aliases(self):
        f = self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", ambiguous_with=["CLX-REQ-0002"])])))
        self.assertIn(("DE-12", "CLX-REQ-0001"), codes(f))

    def test_mixing_ambiguous_with_a_firm_alias_is_named_as_such(self):
        f = self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", "AMBIGUOUS", ambiguous_with=["CLX-REQ-0002"])]),
                            R(2, [al("micromap-resolver-gaps", "RT1")])))
        self.assertTrue(f and all("only AMBIGUOUS aliases" in x.message for x in f), [x.line() for x in f])

    def test_the_same_ambiguous_alias_twice_on_one_record_is_a_duplicate(self):
        a = al("micromap-resolver-gaps", "RT1", "AMBIGUOUS", ambiguous_with=["CLX-REQ-0001"])
        f = self.check(many(R(1, [a, copy.deepcopy(a)])))
        self.assertEqual(only(f), ["DE-05"])
        self.assertTrue(all("only AMBIGUOUS aliases" in x.message for x in f), [x.line() for x in f])

    def test_a_lone_ambiguous_alias_may_not_name_records_that_do_not_carry_it(self):
        f = self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", "AMBIGUOUS", ambiguous_with=["CLX-REQ-0002"])])))
        self.assertEqual(codes(f), [("DE-05", "CLX-REQ-0001")])

    def test_a_single_ambiguous_alias_is_allowed(self):
        self.assertEqual(self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", "AMBIGUOUS")]))), [])

    def test_ambiguous_with_shape(self):
        for bad in ("CLX-REQ-0002", [1], ["not-an-id"]):
            f = self.check(many(R(1, [al("micromap-resolver-gaps", "RT1", "AMBIGUOUS", ambiguous_with=bad)])))
            with self.subTest(repr(bad)):
                self.assertIn("DE-02", only(f))

    def test_findings_sorted_deterministic_inputs_untouched(self):
        r = many(R(2, [al("nope", "x")]), R(1, [al("micromap-resolver-gaps", "RT2")]))
        before = copy.deepcopy(r)
        a, b = self.check(r), self.check(copy.deepcopy(r))
        self.assertEqual(r, before)
        self.assertEqual([x.line() for x in a], [x.line() for x in b])
        self.assertEqual([x.record for x in a], sorted(x.record for x in a))


class ResolveTests(Fx):
    def test_resolution_and_usability(self):
        i = aliases.build_index(recs(**{
            "CLX-REQ-0001": [al("micromap-resolver-gaps", "RT1"), al("audit-c-mutants", "T3b", "REJECTED")],
            "CLX-REQ-0002": [al("micromap-resolver-gaps", "RT2", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT1–RT3"))],
            "CLX-REQ-0003": [al("plan-resolver-gaps-v1", "R1", "HISTORICAL", source=src_ref("v0"))],
            "CLX-REQ-0004": [al("risk-classes", "R1")],
        }))
        r = aliases.resolve(i, "micromap-resolver-gaps", "RT1")
        self.assertEqual((r.status, r.targets, r.usable), ("ACTIVE", ("CLX-REQ-0001",), True))
        r = aliases.resolve(i, "micromap-resolver-gaps", "RT2")
        self.assertEqual((r.status, r.targets, r.usable), ("IMPLIED_BY_RANGE", ("CLX-REQ-0002",), True))
        r = aliases.resolve(i, "audit-c-mutants", "T3b")
        self.assertEqual((r.status, r.targets, r.usable), ("REJECTED", ("CLX-REQ-0001",), False))
        r = aliases.resolve(i, "plan-resolver-gaps-v1", "R1")
        self.assertEqual((r.status, r.targets, r.usable), ("HISTORICAL", ("CLX-REQ-0003",), True))
        self.assertEqual(aliases.resolve(i, "risk-classes", "R1").targets, ("CLX-REQ-0004",))      # same string, other namespace, other record
        r = aliases.resolve(i, "micromap-resolver-gaps", "RT9")
        self.assertEqual((r.status, r.targets, r.usable), ("UNKNOWN", (), False))
        r = aliases.resolve(i, "nope", "RT1")
        self.assertEqual((r.status, r.usable), ("UNKNOWN", False))

    def test_ambiguous_never_resolves_to_one_record(self):
        a = lambda o: al("micromap-resolver-gaps", "RT1", "AMBIGUOUS", ambiguous_with=o)       # noqa: E731
        i = aliases.build_index(recs(**{"CLX-REQ-0002": [a(["CLX-REQ-0001"])], "CLX-REQ-0001": [a(["CLX-REQ-0002"])]}))
        r = aliases.resolve(i, "micromap-resolver-gaps", "RT1")
        self.assertEqual((r.status, r.targets, r.usable), ("AMBIGUOUS", ("CLX-REQ-0001", "CLX-REQ-0002"), False))
        i = aliases.build_index(recs(**{"CLX-REQ-0001": [a([])]}))
        r = aliases.resolve(i, "micromap-resolver-gaps", "RT1")
        self.assertEqual((r.status, r.usable), ("AMBIGUOUS", False))

    def test_a_duplicate_does_not_resolve_silently(self):
        i = aliases.build_index(recs(**{"CLX-REQ-0001": [al("micromap-resolver-gaps", "RT1")], "CLX-REQ-0002": [al("micromap-resolver-gaps", "RT1")]}))
        r = aliases.resolve(i, "micromap-resolver-gaps", "RT1")
        self.assertEqual((r.status, r.targets, r.usable), ("AMBIGUOUS", ("CLX-REQ-0001", "CLX-REQ-0002"), False))

    def test_malformed_aliases_are_not_indexed(self):
        i = aliases.build_index(recs(**{"CLX-REQ-0001": [{"namespace": "x"}, "RT1", {"namespace": "micromap-resolver-gaps", "value": 1, "status": "ACTIVE"}]}))
        self.assertEqual(i, {})
        i = aliases.build_index(recs(**{"CLX-REQ-0001": [{"namespace": "micromap-resolver-gaps", "value": "RT1", "status": "LIVE", "source": src_ref()}]}))
        self.assertEqual(i, {})


class MoveTests(unittest.TestCase):
    def test_pure_move_rules(self):
        base = {("ns", "R1"): {"CLX-REQ-0001"}, ("ns", "R2"): {"CLX-REQ-0001"}, ("ns", "R3"): {"CLX-REQ-0001", "CLX-REQ-0002"}}
        same = copy.deepcopy(base)
        self.assertEqual(aliases.check_moves(base, same), [])
        head = {("ns", "R1"): {"CLX-REQ-0009"}, ("ns", "R2"): set(), ("ns", "R3"): {"CLX-REQ-0002", "CLX-REQ-0003"}, ("ns", "R4"): {"CLX-REQ-0001"}}
        f = aliases.check_moves(base, head)
        self.assertEqual([(x.code, x.record) for x in f], [("DE-06", "ns:R1"), ("DE-06", "ns:R3")])      # R2 merely removed from X, R4 is new

    def test_a_holder_dropping_out_of_a_shared_alias_is_not_a_move(self):
        self.assertEqual(aliases.check_moves({("ns", "R5"): {"A", "B"}}, {("ns", "R5"): {"B"}}), [])

    def test_added_holder_without_loss_is_not_a_move(self):
        self.assertEqual(aliases.check_moves({("ns", "R1"): {"A"}}, {("ns", "R1"): {"A", "B"}}), [])

    def test_alias_map(self):
        m = aliases.alias_map(recs(**{"CLX-REQ-0001": [al("a", "X"), {"bad": 1}], "CLX-REQ-0002": [al("a", "X", "AMBIGUOUS")]}))
        self.assertEqual(m, {("a", "X"): {"CLX-REQ-0001", "CLX-REQ-0002"}})


class GitMoveTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.repo = Path(self._t.name)
        git(self.repo, "init", "-q", "-b", "main")
        new_root(self.repo)
        put(self.repo, "REQ", 1, obj=rec("REQ", 1, aliases=[al("audit-c-mutants", "R1")]))
        put(self.repo, "REQ", 2)
        commit_all(self.repo, "base")
        self.base = git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def test_store_base_objects(self):
        objs = store.base_objects(self.repo, self.base)
        self.assertEqual(sorted(objs), ["CLX-REQ-0001", "CLX-REQ-0002"])
        self.assertEqual(objs["CLX-REQ-0001"]["aliases"][0]["value"], "R1")

    def test_store_base_objects_skips_unreadable_and_rejects_a_bad_ref(self):
        (self.repo / "records" / "REQ" / "CLX-REQ-0003.json").write_bytes(b"{nope")
        canon.write_record(self.repo / "records" / "REQ" / "CLX-REQ-0004.json", {"x": 1})
        (self.repo / "records" / "REQ" / "notes.txt").write_text("n\n", encoding="utf-8")
        canon.write_record(self.repo / "records" / "REQ" / "CLX-REQ-0009.json.bak", rec("REQ", 9))      # valid JSON, but not a record file
        commit_all(self.repo, "broken")
        h = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(sorted(store.base_objects(self.repo, h)), ["CLX-REQ-0001", "CLX-REQ-0002"])
        with self.assertRaises(store.StoreError):
            store.base_objects(self.repo, "nope")

    def test_alias_moved_to_another_record_is_de06(self):
        put(self.repo, "REQ", 1, obj=rec("REQ", 1))
        put(self.repo, "REQ", 2, obj=rec("REQ", 2, aliases=[al("audit-c-mutants", "R1")]))
        head = {r.id: r.obj for r in store.load(self.repo).records.values()}
        f = aliases.check_moves_against_base(self.repo, head, self.base)
        self.assertEqual([(x.code, x.record) for x in f], [("DE-06", "audit-c-mutants:R1")])

    def test_alias_left_in_place_is_fine(self):
        head = {r.id: r.obj for r in store.load(self.repo).records.values()}
        self.assertEqual(aliases.check_moves_against_base(self.repo, head, self.base), [])


class CliTests(Fx):
    def setUp(self):
        super().setUp()
        self.reg = Path(self._t.name) / "reg"
        for t in store.STORED_TYPES:
            (self.reg / "records" / t).mkdir(parents=True)
        put(self.reg, "REQ", 1, obj=rec("REQ", 1, aliases=[al("micromap-resolver-gaps", "RT1")]))
        put(self.reg, "REQ", 2, obj=rec("REQ", 2, aliases=[al("micromap-resolver-gaps", "RT2", "IMPLIED_BY_RANGE", range_source=src_ref(quote="RT1–RT3"))]))
        self.nsp, self.srcp = Path(self._t.name) / "ns.json", Path(self._t.name) / "src.json"
        canon.write_record(self.nsp, self.ns)
        canon.write_record(self.srcp, self.src)
        self.args = ["check", "--root", str(self.reg), "--namespaces", str(self.nsp), "--catalog", str(self.srcp), "--source-root", f"ws={self.ws}"]

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = aliases.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_ok(self):
        code, out, err = self.run_cli(*self.args)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("aliases: OK", out)

    def test_data_errors_exit_1(self):
        put(self.reg, "REQ", 3, obj=rec("REQ", 3, aliases=[al("micromap-resolver-gaps", "RT2")]))
        code, out, _ = self.run_cli(*self.args)
        self.assertEqual(code, 1)
        self.assertIn("DE-13", out)

    def test_store_errors_are_reported_too(self):
        put(self.reg, "REQ", 3, obj=rec("REQ", 4))
        code, out, _ = self.run_cli(*self.args)
        self.assertEqual(code, 1)
        self.assertIn("DE-02", out)

    def test_invalid_namespace_or_source_catalog_exits_1_and_missing_exits_3(self):
        bad = copy.deepcopy(self.ns)
        bad["namespaces"][0]["status"] = "x"
        canon.write_record(self.nsp, bad, overwrite=True)
        self.assertEqual(self.run_cli(*self.args)[0], 1)
        self.assertEqual(self.run_cli("check", "--root", str(self.reg), "--namespaces", str(self.nsp.with_name("none.json")), "--catalog", str(self.srcp))[0], 3)

    def test_base_check(self):
        git(self.reg, "init", "-q", "-b", "main")
        commit_all(self.reg, "base")
        base = git(self.reg, "rev-parse", "HEAD").stdout.strip()
        put(self.reg, "REQ", 1, obj=rec("REQ", 1))
        put(self.reg, "REQ", 2, obj=rec("REQ", 2, aliases=[al("micromap-resolver-gaps", "RT1")]))
        code, out, _ = self.run_cli(*self.args, "--base", base)
        self.assertEqual(code, 1)
        self.assertIn("DE-06", out)

    def test_a_wrong_authority_quote_is_reported_by_the_cli(self):
        bad = copy.deepcopy(self.ns)
        bad["namespaces"][0]["authority"]["quote"] = "RT1-RT3 with the wrong dash"
        canon.write_record(self.nsp, bad, overwrite=True)
        code, out, _ = self.run_cli(*self.args)
        self.assertEqual(code, 1)
        self.assertIn("DE-13", out)

    def test_malformed_catalogs_never_reach_the_alias_checks(self):
        bad = copy.deepcopy(self.src)
        del bad["sources"][0]["versions"][0]["location"]
        canon.write_record(self.srcp, bad, overwrite=True)
        code, out, err = self.run_cli(*self.args)
        self.assertEqual((code, err), (1, ""))
        self.assertIn("missing field 'location'", out)

    def test_bad_source_root_argument_exits_3(self):
        self.assertEqual(self.run_cli("check", "--root", str(self.reg), "--namespaces", str(self.nsp), "--catalog", str(self.srcp), "--source-root", "x")[0], 3)


if __name__ == "__main__":
    unittest.main()
