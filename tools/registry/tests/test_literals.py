"""IMP2-07a - literal capture of original states, references and result phrases: recorded, never interpreted (tier B, the no-loss rule is tier A)."""
import random
import unittest

from clxreg import literals


def scan(text):
    return literals.scan_literals(text)


def got(text, cls=None):
    return [(m.text, m.cls) for m in scan(text) if cls is None or m.cls == cls]


def texts(text, cls=None):
    return [t for t, _ in got(text, cls)]


class StateWordTests(unittest.TestCase):
    def test_every_state_word_is_found(self):
        for w in literals.STATE_WORDS:
            with self.subTest(w):
                self.assertEqual(got(f"x {w} y", "STATE_WORD"), [(w, "STATE_WORD")])

    def test_the_words_of_the_plan_are_all_listed(self):
        for w in ("DONE", "PARTIAL", "PLANNED", "BLOCKED", "UNKNOWN", "OPEN", "VERIFIED", "ASSERTED", "PROVISIONAL", "RATIFIED", "PROPOSED", "DRAFT",
                  "HISTORICAL", "NOT RUN", "SUPERSEDED", "WITHDRAWN", "CLOSED", "FIXED", "REJECTED"):
            self.assertIn(w, literals.STATE_WORDS)

    def test_boundaries_and_case(self):
        for text in ("UNDONE", "DONEX", "PRE-DONE_", "done", "Done", "OPENED", "REOPEN", "DRAFTS", "1OPEN"):
            with self.subTest(text):
                self.assertEqual(texts(text, "STATE_WORD"), [], text)

    def test_hyphen_slash_and_punctuation_are_boundaries(self):
        self.assertEqual(texts("RATIFIED-MARKED", "STATE_WORD"), ["RATIFIED"])
        self.assertEqual(texts("(OPEN), DONE; PLANNED/BLOCKED.", "STATE_WORD"), ["OPEN", "DONE", "PLANNED", "BLOCKED"])

    def test_two_word_state_and_every_occurrence(self):
        self.assertEqual(texts("NOT RUN and NOT RUN and OPEN OPEN", "STATE_WORD"), ["NOT RUN", "NOT RUN", "OPEN", "OPEN"])

    def test_the_longer_phrase_does_not_hide_the_shorter_word(self):
        self.assertEqual(texts("NOT RUN", "STATE_WORD"), ["NOT RUN"])


class ReferenceTests(unittest.TestCase):
    def test_pull_request_references(self):
        self.assertEqual(texts("see PR #17 and #18, (#19) PR #20.", "REFERENCE"), ["PR #17", "#18", "#19", "PR #20"])
        for text in ("C#9", "a#1", "#x", "#"):
            self.assertEqual(texts(text, "REFERENCE"), [], text)

    def test_commit_and_content_hashes(self):
        h40 = "227733484a1851bc512f7ba3fef6dd78b6d0e5da"
        h64 = "8178ab3cf2031b5bf1faf4433eff54f4b9becb8ccb04ccc99ae8d4639710f8d3"
        self.assertEqual(texts(f"at 0ca9b73, 2277334 and {h40} then {h64}.", "REFERENCE"), ["0ca9b73", "2277334", h40, h64])

    def test_things_that_only_look_like_hashes_are_not(self):
        for text in ("abcdefa", "0ca9b6", "faceded", "0CA9B73", "g0ca9b73", "0ca9b73g", "a" * 65 + "1", "12345678", "123456", "20261101"):
            with self.subTest(text[:20]):
                self.assertEqual(texts(text, "REFERENCE"), [], text)

    def test_a_decimal_only_seven_character_hash_is_kept_because_it_cannot_be_told_from_a_number(self):
        self.assertEqual(texts("at 2277334 and 12345678 and 123456", "REFERENCE"), ["2277334"])
        self.assertEqual(scan("2277334")[0].patterns, ("hash-digits-7",))

    def test_ci_run_ids(self):
        self.assertEqual(texts("CI run 40066814847 passed; run 12345678", "REFERENCE"), ["CI run 40066814847", "run 12345678"])
        self.assertEqual(texts("run 123456", "REFERENCE"), [])

    def test_pr_numbers_up_to_five_digits(self):
        self.assertEqual(texts("#1 #12345", "REFERENCE"), ["#1", "#12345"])
        self.assertEqual(texts("#123456", "REFERENCE"), [])

    def test_a_seven_digit_run_id_is_a_number_not_a_run(self):
        self.assertEqual(texts("run 1234567", "REFERENCE"), ["1234567"])
        self.assertEqual(texts("run 12345678", "REFERENCE"), ["run 12345678"])

    def test_every_file_extension_of_the_list(self):
        for ext in ("cs", "md", "py", "json", "yml", "yaml", "txt", "sdoc", "ods"):
            with self.subTest(ext):
                self.assertEqual(texts(f"see f.{ext}:7.", "REFERENCE"), [f"f.{ext}:7"])

    def test_test_names_with_the_singular_suffix(self):
        self.assertEqual(texts("FooTest and BarTests", "REFERENCE"), ["FooTest", "BarTests"])

    def test_same_span_and_class_from_two_patterns_is_one_literal_with_both_patterns(self):
        import re
        from unittest import mock
        fake = [(literals.REFERENCE, "alpha", re.compile("ab")), (literals.REFERENCE, "beta", re.compile("a[b]")), (literals.STATE_WORD, "gamma", re.compile("ab"))]
        with mock.patch.object(literals, "_PATTERNS", fake):
            got_ = [(m.text, m.cls, m.patterns) for m in literals.scan_literals("x ab y")]
        self.assertEqual(got_, [("ab", "REFERENCE", ("alpha", "beta")), ("ab", "STATE_WORD", ("gamma",))])

    def test_file_line_references(self):
        self.assertEqual(texts("GitProcessRunner.cs:120 and docs/a.md:5-9 and tests\\x.py:3", "REFERENCE"),
                         ["GitProcessRunner.cs:120", "docs/a.md:5-9", "tests\\x.py:3"])
        self.assertEqual(texts("a.md: no line, b.docx:4", "REFERENCE"), [])

    def test_test_names(self):
        self.assertEqual(texts("GitSnapshotCleanFilterTests and test_unit_path and GitSnapshotCleanFilterTests.Runs", "REFERENCE"),
                         ["GitSnapshotCleanFilterTests", "test_unit_path", "GitSnapshotCleanFilterTests.Runs"])
        self.assertEqual(texts("Tests are good", "REFERENCE"), [])

    def test_the_pattern_that_found_it_is_recorded_without_meaning(self):
        m = scan("PR #17")[0]
        self.assertEqual((m.cls, m.patterns), ("REFERENCE", ("pr",)))
        self.assertEqual(scan("CI run 40066814847")[0].patterns, ("ci-run",))
        self.assertEqual(scan("0ca9b73")[0].patterns, ("hash",))


class ResultPhraseTests(unittest.TestCase):
    def test_golden_samples(self):
        self.assertEqual(texts("330 of 330 PASS", "RESULT_PHRASE"), ["330 of 330", "PASS"])
        self.assertEqual(texts("PASSED, FAILED and FAIL, 3 of 7", "RESULT_PHRASE"), ["PASSED", "FAILED", "FAIL", "3 of 7"])

    def test_boundaries(self):
        for text in ("PASSING", "BYPASS", "FAILURE", "3 of", "of 3", "x3 of 4", "3 of 4x", "passed"):
            self.assertEqual(texts(text, "RESULT_PHRASE"), [], text)

    def test_numbers_in_other_contexts_are_not_phrases(self):
        self.assertEqual(texts("10 of the 20 items", "RESULT_PHRASE"), [])


class GoldenLineTests(unittest.TestCase):
    def test_a_realistic_line_keeps_every_literal(self):
        line = "CI run 40066814847 on 2277334: 330 of 330 PASS, PR #16 DONE (GitSnapshotCleanFilterTests) in GitProcessRunner.cs:120"
        got_ = {(m.text, m.cls) for m in scan(line)}
        for want in (("CI run 40066814847", "REFERENCE"), ("2277334", "REFERENCE"), ("330 of 330", "RESULT_PHRASE"), ("PASS", "RESULT_PHRASE"),
                     ("PR #16", "REFERENCE"), ("DONE", "STATE_WORD"), ("GitSnapshotCleanFilterTests", "REFERENCE"), ("GitProcessRunner.cs:120", "REFERENCE")):
            self.assertIn(want, got_)

    def test_nothing_is_normalised(self):
        m = [x for x in scan("a  DONE\t") if x.cls == "STATE_WORD"][0]
        self.assertEqual((m.text, m.start, m.end), ("DONE", 3, 7))

    def test_every_match_is_the_exact_slice_and_the_output_is_deterministic(self):
        rnd = random.Random(11)
        parts = ["DONE", "OPEN", "PR #", "17", " ", "-", "0ca9b73", "run ", "40066814847", "CI ", "330", " of ", "PASS", ".cs:", "a", "Tests", "NOT ", "RUN"]
        for _ in range(300):
            text = "".join(rnd.choice(parts) for _ in range(rnd.randint(1, 12)))
            a, b = scan(text), scan(text)
            self.assertEqual(a, b)
            self.assertEqual([(m.start, m.end, m.cls) for m in a], sorted((m.start, m.end, m.cls) for m in a))
            for m in a:
                self.assertEqual(text[m.start:m.end], m.text)

    def test_empty_text(self):
        self.assertEqual(scan(""), [])


if __name__ == "__main__":
    unittest.main()
