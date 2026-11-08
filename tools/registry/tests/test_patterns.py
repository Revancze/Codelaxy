"""IMP2-06 - label patterns from the namespace catalog, ambiguity, ranges, second pass; nothing found may be dropped (tier A)."""
import copy
import random
import re
import unittest

from clxreg import namespaces, patterns, textsource


def ns(key, pattern, maps_to="REQ", status="LIVE", distinct=()):
    return {"key": key, "label_pattern": pattern, "meaning": key, "authority": {"source": "doc", "version": "v1"}, "status": status,
            "maps_to": maps_to, "distinct_from": list(distinct)}


def catalog():
    return {"schema": namespaces.SCHEMA, "namespaces": [
        ns("micromap-resolver-gaps", "RT[0-9]+"),
        ns("plan-resolver-gaps-v1", "R[0-9]+", status="FROZEN"),
        ns("risk-classes", "R[0-4]", maps_to="EXTERNAL"),
        ns("micromap-findings", r"F(?:1[0-4]|[1-9])[ab]?|T[1-3]|S[12]|MSYS2-COMPAT"),
        ns("bare-step-label", "M[0-5][a-d]?"),
        ns("roadmap-ods-ids", r"P1\.2-[A-Z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]"),
        ns("gate-or-experiment-label", "E[12]"),
        ns("micromap-gates", "E1-[1-8]"),
        ns("micromap-run-scenarios", "RUN-[1-5]"),
    ]}


SRC_VALID_NS = {"micromap-resolver-gaps", "plan-resolver-gaps-v1", "risk-classes", "micromap-findings", "bare-step-label", "roadmap-ods-ids",
                "gate-or-experiment-label", "micromap-gates", "micromap-run-scenarios"}


def scan(text, cat=None):
    return patterns.scan_text(text, patterns.compile_namespaces(cat or catalog()))


def view(ms):
    return [(m.text, m.cls, m.namespaces) for m in ms]


def texts(ms, cls=None):
    return [m.text for m in ms if cls is None or m.cls == cls]


class CompileTests(unittest.TestCase):
    def test_every_namespace_is_compiled_in_catalog_order(self):
        self.assertEqual([k for k, _ in patterns.compile_namespaces(catalog())][:2], ["micromap-resolver-gaps", "plan-resolver-gaps-v1"])

    def test_invalid_or_empty_matching_patterns_are_refused(self):
        for bad in ("R[0-", "R*", ""):
            c = catalog()
            c["namespaces"][0]["label_pattern"] = bad
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    patterns.compile_namespaces(c)

    def test_malformed_catalog_is_refused(self):
        for bad in (None, [], {}, {"namespaces": "x"}, {"namespaces": [1]}, {"namespaces": [{"key": "a"}]}):
            with self.assertRaises(ValueError):
                patterns.compile_namespaces(bad)


class LabelTests(unittest.TestCase):
    def test_zero_width_namespace_match_is_rejected(self):
        cat = {
            "schema": namespaces.SCHEMA,
            "namespaces": [
                ns("probe", r"RT[1-3]|(?=!)"),
            ],
        }

        # Normal match must remain valid.
        self.assertEqual(
            view(scan("RT2", cat)),
            [("RT2", "LABEL", ("probe",))],
        )

        # The zero-width alternative must fail closed.
        with self.assertRaisesRegex(ValueError, "zero-width"):
            scan("RT1 !", cat)

    def test_a_single_namespace_label(self):
        ms = scan("see RT1 here")
        self.assertEqual(view(ms), [("RT1", "LABEL", ("micromap-resolver-gaps",))])
        self.assertEqual((ms[0].start, ms[0].end), (4, 7))

    def test_the_same_string_in_two_namespaces_is_one_ambiguous_match_never_merged(self):
        ms = scan("risk R1 is high")
        self.assertEqual(view(ms), [("R1", "LABEL", ("plan-resolver-gaps-v1", "risk-classes"))])

    def test_a_label_that_only_one_namespace_pattern_covers_stays_unambiguous(self):
        self.assertEqual(view(scan("R7")), [("R7", "LABEL", ("plan-resolver-gaps-v1",))])

    def test_boundaries_letters_digits_underscore_and_unicode_letters_next_to_a_label(self):
        for text in ("XRT1", "RT1x", "_RT1", "RT1_", "áRT1", "RT1á", "1RT1"):
            with self.subTest(text):
                self.assertNotIn("micromap-resolver-gaps", [n for m in scan(text) if m.cls == "LABEL" for n in m.namespaces], text)

    def test_longer_numbers_are_whole_labels(self):
        self.assertEqual(view(scan("RT10")), [("RT10", "LABEL", ("micromap-resolver-gaps",))])

    def test_a_label_after_a_hyphen_is_found(self):
        ms = scan("RT1-RT3")
        self.assertEqual(texts(ms, "LABEL"), ["RT1", "RT3"])

    def test_every_occurrence_on_a_line_is_kept_with_its_own_position(self):
        ms = scan("RT1 and RT1, then F11 F12 F11")
        self.assertEqual([(m.text, m.start) for m in ms if m.cls == "LABEL"], [("RT1", 0), ("RT1", 8), ("F11", 18), ("F12", 22), ("F11", 26)])

    def test_a_failed_boundary_does_not_hide_a_later_overlapping_match(self):
        c = {"schema": namespaces.SCHEMA, "namespaces": [ns("a", "AB"), ns("b", "BC")]}
        self.assertEqual([(m.text, m.start) for m in scan("xAB BC", c)], [("BC", 4)])
        self.assertEqual([(m.text, m.start) for m in scan("ABC", c)], [])

    def test_alternation_and_suffix_patterns(self):
        self.assertEqual(texts(scan("F13a F14 F9b"), "LABEL"), ["F13a", "F14", "F9b"])
        self.assertEqual(texts(scan("MSYS2-COMPAT"), "LABEL"), ["MSYS2-COMPAT"])

    def test_case_sensitive(self):
        self.assertEqual(scan("rt1 Rt1"), [])


class ContainmentTests(unittest.TestCase):
    def test_a_shorter_match_inside_a_longer_identifier_is_kept_inside_it_not_dropped(self):
        ms = scan("step P1.2-M3d now")
        outer = [m for m in ms if m.text == "P1.2-M3d"]
        self.assertEqual(len(outer), 1)
        self.assertEqual(outer[0].namespaces, ("roadmap-ods-ids",))
        inner = {(c.text, c.cls) for c in outer[0].contained}
        self.assertIn(("M3d", "LABEL"), inner)
        self.assertEqual(texts(ms), ["P1.2-M3d"])                                  # inner matches are not separate entries

    def test_the_contained_match_keeps_its_own_position_and_namespaces(self):
        outer = next(m for m in scan("P1.2-M3d") if m.text == "P1.2-M3d")
        c = next(c for c in outer.contained if c.text == "M3d")
        self.assertEqual((c.start, c.end, c.namespaces), (5, 8, ("bare-step-label",)))

    def test_gate_label_contains_the_experiment_label(self):
        ms = scan("gate E1-1 passed")
        self.assertEqual(view(ms), [("E1-1", "LABEL", ("micromap-gates",))])
        self.assertIn("E1", [c.text for c in ms[0].contained])

    def test_nested_containment_is_flattened_onto_the_outermost(self):
        c = {"schema": namespaces.SCHEMA, "namespaces": [ns("a", "A-B-C-D"), ns("b", "B-C-D"), ns("c", "C-D")]}
        ms = scan("A-B-C-D", c)
        self.assertEqual(texts(ms), ["A-B-C-D"])
        self.assertEqual(sorted(x.text for x in ms[0].contained), ["B-C-D", "C-D"])

    def test_partial_overlaps_are_both_kept(self):
        c = {"schema": namespaces.SCHEMA, "namespaces": [ns("a", "AB-CD"), ns("b", "CD-EF")]}
        ms = scan("AB-CD-EF", c)
        self.assertEqual(sorted(texts(ms)), ["AB-CD", "CD-EF"])
        self.assertTrue(all(not m.contained for m in ms))


class RangeTests(unittest.TestCase):
    def test_a_range_is_one_range_match_and_its_members_are_not_invented(self):
        ms = scan("RT1–RT3 killed")
        self.assertEqual(texts(ms, "RANGE"), ["RT1–RT3"])
        self.assertEqual(texts(ms, "LABEL"), ["RT1", "RT3"])
        self.assertNotIn("RT2", texts(ms))

    def test_matches_come_out_in_position_order_with_ranges_between_their_ends(self):
        self.assertEqual(texts(scan("RT1–RT3")), ["RT1", "RT1–RT3", "RT3"])

    def test_range_forms(self):
        for text, ends in (("R1–R3", ("R1", "R3")), ("F9–F14", ("F9", "F14")), ("M0–M6", ("M0", "M6")), ("RT1…RT3", ("RT1", "RT3")),
                           ("RT1-RT3", ("RT1", "RT3")), ("RT1..RT3", ("RT1", "RT3")), ("RT1 – RT3", ("RT1", "RT3")), ("RT1—RT3", ("RT1", "RT3")), ("RT1– 3", ("RT1", "3")),
                           ("F9–14", ("F9", "14"))):
            ms = [m for m in scan(text) if m.cls == "RANGE"]
            with self.subTest(text):
                if ends is None:
                    self.assertEqual(ms, [])
                else:
                    self.assertEqual(len(ms), 1)
                    self.assertEqual(ms[0].ends, ends)
                    self.assertEqual(ms[0].text, text)

    def test_hyphen_between_different_prefixes_is_not_a_range(self):
        self.assertEqual([m for m in scan("RT1-R3") if m.cls == "RANGE"], [])
        self.assertEqual([m for m in scan("E1-1") if m.cls == "RANGE"], [])

    def test_several_ranges_on_one_line(self):
        self.assertEqual(texts(scan("RT1–RT3 and R1–R3"), "RANGE"), ["RT1–RT3", "R1–R3"])

    def test_range_boundaries(self):
        self.assertEqual([m for m in scan("XRT1–RT3") if m.cls == "RANGE"], [])
        self.assertEqual([m for m in scan("RT1–RT3x") if m.cls == "RANGE"], [])


class SecondPassTests(unittest.TestCase):
    def test_label_like_tokens_of_no_namespace_are_reported(self):
        ms = scan("Q99 and S3267 and CDX0001")
        self.assertEqual(view(ms), [("Q99", "UNCLASSIFIED", ()), ("S3267", "UNCLASSIFIED", ()), ("CDX0001", "UNCLASSIFIED", ())])

    def test_tokens_around_a_hyphen_are_both_kept(self):
        self.assertEqual(texts(scan("Q99-Q100"), "UNCLASSIFIED"), ["Q99", "Q100"])
        self.assertEqual(texts(scan("see X1-Y2-Z3"), "UNCLASSIFIED"), ["X1", "Y2", "Z3"])

    def test_known_labels_are_not_reported_twice(self):
        self.assertEqual(view(scan("RT1")), [("RT1", "LABEL", ("micromap-resolver-gaps",))])

    def test_a_generic_token_with_a_lowercase_suffix(self):
        self.assertEqual(texts(scan("RT1a"), "UNCLASSIFIED"), ["RT1a"])

    def test_generic_tokens_inside_a_longer_identifier_are_contained(self):
        ms = scan("P1.2-M3d")
        self.assertIn(("P1", "UNCLASSIFIED"), {(c.text, c.cls) for c in ms[0].contained})

    def test_words_inside_words_are_not_tokens(self):
        self.assertEqual(scan("abcDEF12 x"), [])


class NoLossProperty(unittest.TestCase):
    """Whatever the line looks like, every boundary-valid match of every matcher is an entry or inside one."""

    ALPHABET = ["RT", "R", "F", "M", "E", "P1.2-", "T", "S", "Q", "1", "2", "3", "10", "14", "a", "b", "d", "-", "–", "…", " ", " ", ",", ".",
                "X", "_", "á", "MSYS2-COMPAT", "RUN-", "COMPAT"]

    def raw_spans(self, text, cat):
        spans = set()
        for key, rx in patterns.compile_namespaces(cat):
            pos = 0
            while True:
                m = rx.search(text, pos)
                if not m:
                    break
                s, e = m.span()
                ok = not (s > 0 and textsource.is_word(text[s - 1])) and not (e < len(text) and textsource.is_word(text[e]))
                if ok:
                    spans.add((s, e))
                pos = e if ok else s + 1
        return spans

    def test_no_boundary_valid_label_match_is_lost(self):
        rnd = random.Random(20261101)
        cat = catalog()
        for _ in range(400):
            text = "".join(rnd.choice(self.ALPHABET) for _ in range(rnd.randint(1, 14)))
            ms = patterns.scan_text(text, patterns.compile_namespaces(cat))
            seen = set()
            for m in ms:
                seen.add((m.start, m.end))
                for c in m.contained:
                    seen.add((c.start, c.end))
            missing = self.raw_spans(text, cat) - seen
            self.assertEqual(missing, set(), repr(text))

    def test_output_is_deterministic_and_sorted_by_position(self):
        rnd = random.Random(7)
        cat = catalog()
        comp = patterns.compile_namespaces(cat)
        for _ in range(100):
            text = "".join(rnd.choice(self.ALPHABET) for _ in range(rnd.randint(1, 14)))
            a, b = patterns.scan_text(text, comp), patterns.scan_text(text, comp)
            self.assertEqual(a, b)
            self.assertEqual([(m.start, m.end) for m in a], sorted((m.start, m.end) for m in a))
            for m in a:
                self.assertEqual(text[m.start:m.end], m.text)


class AmbiguityRuleTests(unittest.TestCase):
    def rules(self, *r):
        return {"schema": patterns.AMBIGUITY_SCHEMA, "rules": list(r)}

    def rule(self, namespace="bare-step-label", **kw):
        d = {"namespace": namespace, "meanings": ["P1.2 step without prefix", "superseded roadmap step"], "basis": "INVENTORY C-07"}
        d.update(kw)
        return d

    def test_good_rules(self):
        self.assertEqual(patterns.validate_ambiguity(self.rules(self.rule()), catalog()), [])

    def test_shape(self):
        bad = {"no namespace": lambda r: r.pop("namespace"), "one meaning": lambda r: r.update(meanings=["x"]), "duplicate meanings": lambda r: r.update(meanings=["x", "x"]),
               "empty meaning": lambda r: r.update(meanings=["x", ""]), "meanings not list": lambda r: r.update(meanings="xy"),
               "no basis": lambda r: r.pop("basis"), "empty basis": lambda r: r.update(basis=""), "unknown field": lambda r: r.update(x=1),
               "value not str": lambda r: r.update(value=1)}
        for name, mutate in bad.items():
            r = self.rule()
            mutate(r)
            with self.subTest(name):
                self.assertIn("DE-02", {f.code for f in patterns.validate_ambiguity(self.rules(r), catalog())})
        for top in (None, [], {"schema": "x", "rules": []}, {"schema": patterns.AMBIGUITY_SCHEMA}, {"schema": patterns.AMBIGUITY_SCHEMA, "rules": {}},
                    {"schema": patterns.AMBIGUITY_SCHEMA, "rules": [], "x": 1}):
            self.assertIn("DE-02", {f.code for f in patterns.validate_ambiguity(top, catalog())})

    def test_unknown_namespace_and_value_that_does_not_fit(self):
        self.assertEqual({f.code for f in patterns.validate_ambiguity(self.rules(self.rule("nope")), catalog())}, {"DE-03"})
        self.assertEqual({f.code for f in patterns.validate_ambiguity(self.rules(self.rule(value="Q9")), catalog())}, {"DE-05"})
        self.assertEqual(patterns.validate_ambiguity(self.rules(self.rule(value="M3d")), catalog()), [])

    def test_duplicate_rules(self):
        f = patterns.validate_ambiguity(self.rules(self.rule(), self.rule()), catalog())
        self.assertEqual({x.code for x in f}, {"DE-01"})
        self.assertEqual(patterns.validate_ambiguity(self.rules(self.rule(), self.rule(value="M3d")), catalog()), [])

    def test_lookup_prefers_the_value_rule(self):
        r = self.rules(self.rule(), self.rule(value="M3d", meanings=["a", "b"]))
        self.assertEqual(patterns.ambiguity_meanings(r, "bare-step-label", "M3d"), ["a", "b"])
        self.assertEqual(patterns.ambiguity_meanings(r, "bare-step-label", "M1"), ["P1.2 step without prefix", "superseded roadmap step"])
        self.assertIsNone(patterns.ambiguity_meanings(r, "risk-classes", "R1"))
        self.assertIsNone(patterns.ambiguity_meanings(None, "bare-step-label", "M1"))

    def test_inputs_are_not_modified(self):
        r, c = self.rules(self.rule(value="Q9")), catalog()
        before = (copy.deepcopy(r), copy.deepcopy(c))
        patterns.validate_ambiguity(r, c)
        self.assertEqual((r, c), before)


class CollisionCases(unittest.TestCase):
    """INVENTORY C-01 ... : the same string with several meanings is never resolved by the scanner."""

    def test_c01_r1_to_r3_appear_in_several_namespaces(self):
        for label in ("R1", "R2", "R3"):
            m = scan(label)[0]
            self.assertEqual(m.namespaces, ("plan-resolver-gaps-v1", "risk-classes"), label)

    def test_c02_rt_range(self):
        ms = scan("RT1–RT3")
        self.assertEqual(sorted(texts(ms)), ["RT1", "RT1–RT3", "RT3"])

    def test_c05_e1_alone_and_in_gate_labels(self):
        ms = scan("E1 and E1-2 and E2")
        self.assertEqual([(m.text, m.namespaces) for m in ms], [("E1", ("gate-or-experiment-label",)), ("E1-2", ("micromap-gates",)), ("E2", ("gate-or-experiment-label",))])

    def test_c07_bare_step_label_versus_prefixed_step_label(self):
        ms = scan("M3d and P1.2-M3d")
        self.assertEqual([(m.text, m.namespaces) for m in ms], [("M3d", ("bare-step-label",)), ("P1.2-M3d", ("roadmap-ods-ids",))])


if __name__ == "__main__":
    unittest.main()
