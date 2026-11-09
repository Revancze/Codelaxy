"""IMP2-04 - literal label / quote search in source text and range parsing (tier A: it decides whether an alias is evidenced)."""
import unittest

from clxreg import textsource as ts


def at(text, label):
    return [(o.line, o.column) for o in ts.find_label(text, label)]


class DecodeTests(unittest.TestCase):
    def test_strict_utf8(self):
        self.assertEqual(ts.decode("RT1–RT3 ř".encode("utf-8")), "RT1–RT3 ř")

    def test_invalid_bytes_are_an_error_not_replaced(self):
        for raw in (b"\xff\xfe", b"ab\x80cd", "ř".encode("cp1250")):
            with self.subTest(raw):
                with self.assertRaises(ts.SourceTextError):
                    ts.decode(raw)

    def test_bom_is_kept_so_offsets_match_the_bytes(self):
        self.assertEqual(ts.decode(b"\xef\xbb\xbfRT1"), "﻿RT1")


class FindLabelTests(unittest.TestCase):
    def test_label_inside_a_range_is_found_at_both_ends_but_the_middle_is_not_a_literal(self):
        self.assertEqual(at("RT1–RT3", "RT1"), [(1, 1)])
        self.assertEqual(at("RT1–RT3", "RT3"), [(1, 5)])
        self.assertEqual(at("RT1–RT3", "RT2"), [])

    def test_hyphen_and_dash_variants_are_boundaries(self):
        for text in ("RT1-RT3", "RT1—RT3", "RT1…RT3", "`RT1`–`RT3`", "(RT1)", "RT1,", "RT1.", "RT1:", "RT1/x"):
            with self.subTest(text):
                self.assertEqual(len(at(text, "RT1")), 1, text)

    def test_letters_digits_and_underscore_next_to_the_label_are_not_a_match(self):
        for text in ("RT10", "XRT1", "_RT1", "RT1_", "ART1", "RT1a", "RT1á", "áRT1", "1RT1", "RT1٣"):
            with self.subTest(text):
                self.assertEqual(at(text, "RT1"), [], text)

    def test_shorter_label_is_not_found_inside_a_longer_one(self):
        self.assertEqual(at("T3b", "T3"), [])
        self.assertEqual(at("T3b", "T3b"), [(1, 1)])
        self.assertEqual(at("T3 and T3b", "T3"), [(1, 1)])

    def test_labels_with_inner_punctuation(self):
        self.assertEqual(at("see P1.2-M3d.", "P1.2-M3d"), [(1, 5)])
        self.assertEqual(at("P1.2-M3dx", "P1.2-M3d"), [])

    def test_every_occurrence_with_line_and_column_for_lf_and_crlf(self):
        self.assertEqual(at("a\nRT1\r\nx RT1", "RT1"), [(2, 1), (3, 3)])
        self.assertEqual(at("RT1 RT1", "RT1"), [(1, 1), (1, 5)])

    def test_case_sensitive(self):
        self.assertEqual(at("rt1 Rt1", "RT1"), [])

    def test_offset_is_the_character_offset(self):
        o = ts.find_label("ř RT1", "RT1")[0]
        self.assertEqual((o.offset, o.line, o.column), (2, 1, 3))

    def test_labels_that_cannot_be_searched_are_rejected(self):
        for bad in ("", " ", "R T1", "R\nT1", "RT1 ", "\tRT1"):
            with self.subTest(repr(bad)):
                with self.assertRaises(ValueError):
                    ts.find_label("RT1", bad)

    def test_empty_text_has_no_occurrences(self):
        self.assertEqual(at("", "RT1"), [])


class QuoteTests(unittest.TestCase):
    def test_literal_substring_only(self):
        t = "Status: **RATIFIED** on 2026-10-25.\nNext  line"
        self.assertTrue(ts.contains_quote(t, "**RATIFIED** on 2026-10-25."))
        self.assertTrue(ts.contains_quote(t, "25.\nNext"))
        self.assertFalse(ts.contains_quote(t, "ratified"))                 # case
        self.assertFalse(ts.contains_quote(t, "Next line"))                # whitespace is not normalised
        self.assertFalse(ts.contains_quote(t, "RATIFIED on"))              # markup is not stripped
        self.assertFalse(ts.contains_quote("a\r\nb", "a\nb"))              # line endings are not normalised

    def test_empty_quote_is_rejected_not_trivially_true(self):
        with self.assertRaises(ValueError):
            ts.contains_quote("abc", "")

    def test_dashes_are_not_interchangeable(self):
        self.assertFalse(ts.contains_quote("RT1–RT3", "RT1-RT3"))

    def test_find_quote_gives_every_position(self):
        self.assertEqual([(o.line, o.column) for o in ts.find_quote("ab\nab", "ab")], [(1, 1), (2, 1)])
        self.assertEqual(ts.find_quote("abc", "x"), [])


class RangeTests(unittest.TestCase):
    def test_supported_ranges(self):
        for q, want in {"RT1–RT3": ("RT", 1, 3), "RT1-RT3": ("RT", 1, 3), "RT1—RT3": ("RT", 1, 3), "RT1 – RT3": ("RT", 1, 3),
                        "R1–R3": ("R", 1, 3), "MD1–MD10": ("MD", 1, 10), "T0–T2": ("T", 0, 2)}.items():
            with self.subTest(q):
                self.assertEqual(ts.parse_range(q), want)

    def test_everything_else_is_not_a_range(self):
        for q in ("RT1…RT3", "RT3–RT1", "RT1–RT1", "RT1–R3", "RT1–RT3x", "xRT1–RT3", "RT01–RT03", "RT1", "", "T3b–T5", "RT1 to RT3",
                  "RT1–RT3–RT5", "RT1–", "–RT3", "RT١–RT٣", "RT1٣–RT20", "RT1–RT2٣"):
            with self.subTest(q):
                self.assertIsNone(ts.parse_range(q), q)

    def test_label_between_is_strict_and_prefix_bound(self):
        r = "RT1–RT3"
        self.assertTrue(ts.label_between("RT2", r))
        for label in ("RT1", "RT3", "RT0", "RT4", "R2", "XRT2", "RT02", "RT2a", "rt2", "RT", ""):
            with self.subTest(label):
                self.assertFalse(ts.label_between(label, r), label)

    def test_label_between_with_an_unparseable_range_is_false(self):
        self.assertFalse(ts.label_between("RT2", "RT1…RT3"))
        self.assertTrue(ts.label_between("MD5", "MD1–MD10"))
        self.assertFalse(ts.label_between("MD10", "MD1–MD10"))


if __name__ == "__main__":
    unittest.main()
