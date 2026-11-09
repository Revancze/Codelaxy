"""IMP2-01 - canonical JSON form and digest (tier B; the digest and the strict reader are tier A)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from clxreg import canon

HERE = Path(__file__).resolve().parent
VECTORS = json.loads((HERE / "data" / "vectors.json").read_text(encoding="utf-8"))["vectors"]


class DumpsTests(unittest.TestCase):
    def test_form_is_two_space_indent_sorted_keys_lf_and_trailing_newline(self):
        self.assertEqual(canon.dumps({"b": 1, "a": [1, 2]}), '{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1\n}\n')

    def test_empty_containers_and_scalars(self):
        self.assertEqual(canon.dumps({}), "{}\n")
        self.assertEqual(canon.dumps([]), "[]\n")
        self.assertEqual(canon.dumps({"a": None, "b": True, "c": False}), '{\n  "a": null,\n  "b": true,\n  "c": false\n}\n')

    def test_keys_are_ordered_by_code_point_not_utf16(self):
        c = canon.dumps_compact(json.loads('{"\\ud83d\\ude00": 1, "\\uffff": 2}'))
        self.assertTrue(c.index("￿") < c.index("\U0001F600"))          # U+FFFF < U+1F600 in code points (UTF-16 would reverse them)

    def test_non_ascii_is_written_raw_and_controls_escaped_lowercase(self):
        c = canon.dumps_compact({"d": "RT1–RT3", "c": "\u001f\u007f ", "q": 'a"b\\'})
        self.assertIn("RT1–RT3", c)
        self.assertIn("\\u001f", c)
        self.assertIn("\u007f", c)
        self.assertNotIn("\\u2013", c)

    def test_file_form_also_writes_non_ascii_raw(self):
        self.assertEqual(canon.dumps({"d": "RT1–RT3 ř"}), '{\n  "d": "RT1–RT3 ř"\n}\n')

    def test_floats_nan_non_string_keys_and_foreign_types_are_rejected(self):
        for bad in ({"a": 1.5}, {"a": float("nan")}, {1: "x"}, {"a": (1, 2)}, {"a": {1, 2}}, {"a": b"x"}, {"a": "\ud800"}):
            with self.assertRaises(canon.CanonError, msg=repr(bad)):
                canon.dumps(bad)

    def test_bool_is_not_an_int_in_disguise(self):
        self.assertEqual(canon.dumps_compact({"a": True, "b": 1}), '{"a":true,"b":1}')


class LoadsTests(unittest.TestCase):
    def test_round_trip_is_idempotent(self):
        obj = {"z": [1, {"y": "ř"}], "a": None}
        t = canon.dumps(obj)
        self.assertEqual(canon.loads(t), obj)
        self.assertEqual(canon.dumps(canon.loads(t)), t)

    def test_duplicate_keys_are_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.loads('{"a": 1, "a": 2}')

    def test_nan_infinity_floats_and_bom_are_rejected(self):
        for bad in ('{"a": NaN}', '{"a": Infinity}', '{"a": 1.5}', '{"a": 1e3}', "﻿{}", "{} x", ""):
            with self.assertRaises(canon.CanonError, msg=bad):
                canon.loads(bad)

    def test_is_canonical(self):
        good = canon.dumps({"b": 1, "a": 2})
        self.assertTrue(canon.is_canonical(good))
        self.assertFalse(canon.is_canonical(good.replace("\n", "\r\n")))
        self.assertFalse(canon.is_canonical(good.rstrip("\n")))
        self.assertFalse(canon.is_canonical('{\n    "a": 2,\n    "b": 1\n}\n'))          # 4-space indent
        self.assertFalse(canon.is_canonical('{\n  "b": 1,\n  "a": 2\n}\n'))             # unsorted
        self.assertFalse(canon.is_canonical("not json"))


class VectorTests(unittest.TestCase):
    def test_every_vector(self):
        for v in VECTORS:
            with self.subTest(v["name"]):
                obj = canon.loads(v["input"])
                self.assertEqual(canon.dumps_compact(obj), v["expect_compact"])
                self.assertEqual(canon.digest(obj), v["expect_sha256"])

    def test_vectors_are_not_trivially_empty(self):
        self.assertGreaterEqual(len(VECTORS), 10)


class NormativeDigestTests(unittest.TestCase):
    def examples(self):
        for p in sorted((HERE / "data" / "phase1-examples").glob("*.json")):
            yield p.name, json.loads(p.read_text(encoding="utf-8"))

    def test_digests_of_the_phase1_examples_are_reproduced(self):
        seen = 0
        for name, rec in self.examples():
            with self.subTest(name):
                self.assertEqual(canon.normative_digest(rec), rec["revisions"][-1]["digest"])
                seen += 1
        self.assertEqual(seen, 3)

    def test_non_normative_fields_do_not_change_the_digest_but_normative_ones_do(self):
        _, req = next(x for x in self.examples() if x[1]["type"] == "REQ")
        base = canon.normative_digest(req)
        other = json.loads(json.dumps(req))
        other["title"] = "different title"
        other["note"] = "n"
        other["aliases"] = []
        self.assertEqual(canon.normative_digest(other), base)
        for path in (("statement",), ("applies_to", "platforms"), ("acceptance",)):
            m = json.loads(json.dumps(req))
            if path == ("statement",):
                m["statement"] += "."
            elif path == ("applies_to", "platforms"):
                m["applies_to"]["platforms"] = ["windows"]
            else:
                m["acceptance"][0]["resolved"] = not m["acceptance"][0]["resolved"]
            self.assertNotEqual(canon.normative_digest(m), base, path)

    def test_scenario_digest_covers_procedure_expected_platforms_and_mutant(self):
        _, scn = next(x for x in self.examples() if x[1]["type"] == "SCN")
        base = canon.normative_digest(scn)
        for key, val in (("procedure", "p2"), ("expected", "e2"), ("platforms_required", ["linux"]), ("mutant", {"target": "t"})):
            m = json.loads(json.dumps(scn))
            m[key] = val
            self.assertNotEqual(canon.normative_digest(m), base, key)

    def test_unsupported_type_is_an_error(self):
        with self.assertRaises(canon.CanonError):
            canon.normative_digest({"type": "EVD"})


class WriteTests(unittest.TestCase):
    def test_write_is_lf_only_exclusive_and_canonical(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            canon.write_record(p, {"b": 1, "a": "ř"})
            raw = p.read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertTrue(raw.endswith(b"\n"))
            self.assertTrue(canon.is_canonical(raw.decode("utf-8")))
            with self.assertRaises(FileExistsError):
                canon.write_record(p, {"x": 1})
            canon.write_record(p, {"x": 1}, overwrite=True)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"x": 1})


@unittest.skipUnless(shutil.which("dotnet") and os.environ.get("CLX_SKIP_CROSSLANG") != "1", "dotnet not available or CLX_SKIP_CROSSLANG=1")
class CrossLanguageTests(unittest.TestCase):
    def test_csharp_implementation_agrees_on_every_vector(self):
        src = HERE / "crosslang" / "CanonCheck.cs.txt"
        with tempfile.TemporaryDirectory() as d:
            shutil.copyfile(src, Path(d) / "CanonCheck.cs")
            p = subprocess.run(["dotnet", "run", "CanonCheck.cs", "--", str(HERE / "data" / "vectors.json")], cwd=d, capture_output=True,
                               text=True, encoding="utf-8", timeout=600)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(p.stdout.count(" OK"), len(VECTORS), p.stdout)


if __name__ == "__main__":
    unittest.main()
