#!/usr/bin/env python3
"""Pure-stdlib regression tests for F3 Warning Gate (no dotnet/Git required)."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from warning_gate import GateError, PROJECTS, check, load_baseline, relative_source

BASELINE = Path(__file__).with_name("warning-baseline.json")


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codelaxy-f3-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repository"
        self.repo.mkdir()
        self.sarif = Path(self.temp.name) / "sarif"
        self.sarif.mkdir()
        self.baseline = Path(self.temp.name) / "baseline.json"
        self.baseline.write_bytes(BASELINE.read_bytes())
        self.data = {}
        for project in PROJECTS:
            self.data[project] = {
                "version": "2.1.0",
                "runs": [{
                    "tool": {"driver": {"name": "Microsoft (R) Visual C# Compiler", "rules": [{"id": "CA1502"}]}},
                    "invocations": [{"executionSuccessful": True}],
                    "results": []
                }]
            }
        for (project, source, rule), count in load_baseline(self.baseline).items():
            for _ in range(count):
                self.add_warning(project, source, rule)
        self.flush()

    def add_warning(self, project, source, rule, level="warning", source_uri=None):
        uri = source_uri or (self.repo / source).as_uri()
        self.data[project]["runs"][0]["results"].append({
            "ruleId": rule, "level": level,
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}]
        })

    def flush(self):
        for project in PROJECTS:
            (self.sarif / (project + ".sarif")).write_text(
                json.dumps(self.data[project]), encoding="utf-8")

    def run_check(self):
        with redirect_stdout(io.StringIO()):
            check(self.baseline, self.sarif, str(self.repo))

    def test_f3_01_baseline_passes(self):
        self.run_check()

    def test_f3_02_new_diagnostic_id_fails(self):
        self.add_warning("Codelaxy.Git", "src/Codelaxy.Git/GitProcessRunner.cs", "CA9999")
        self.flush()
        with self.assertRaisesRegex(GateError, "Warning regression"):
            self.run_check()

    def test_f3_03_existing_id_increased_fails(self):
        self.add_warning("Codelaxy.Git", "src/Codelaxy.Git/GitProcessRunner.cs", "MA0051")
        self.flush()
        with self.assertRaisesRegex(GateError, "MA0051"):
            self.run_check()

    def test_f3_04_removed_warning_passes(self):
        self.data["Codelaxy.Tests"]["runs"][0]["results"].pop()
        self.flush()
        self.run_check()

    def test_f3_05_corrupted_baseline_fails(self):
        self.baseline.write_text("{ broken", encoding="utf-8")
        with self.assertRaisesRegex(GateError, "Baseline cannot be read"):
            self.run_check()

    def test_f3_06_missing_or_empty_sarif_fails(self):
        (self.sarif / "Codelaxy.Core.sarif").unlink()
        with self.assertRaisesRegex(GateError, "Missing/unexpected SARIF"):
            self.run_check()
        (self.sarif / "Codelaxy.Core.sarif").write_text("", encoding="utf-8")
        with self.assertRaisesRegex(GateError, "Invalid SARIF"):
            self.run_check()

    def test_f3_07_windows_and_linux_paths(self):
        self.assertEqual(relative_source("file:///C:/checkout/Codelaxy/src/Codelaxy.Git/F.cs",
                                         "C:/checkout/Codelaxy"), "src/Codelaxy.Git/F.cs")
        self.assertEqual(relative_source("file:///home/runner/Codelaxy/src/Codelaxy.Git/F.cs",
                                         "/home/runner/Codelaxy"), "src/Codelaxy.Git/F.cs")

    def test_f3_08_missing_invocation_fails(self):
        self.data["Codelaxy.Core"]["runs"][0]["invocations"] = []
        self.flush()
        with self.assertRaisesRegex(GateError, "execution not proven"):
            self.run_check()

    def test_f3_09_unexpected_sarif_fails(self):
        (self.sarif / "extra.sarif").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(GateError, "Missing/unexpected SARIF"):
            self.run_check()

    def test_f3_10_compiler_error_fails(self):
        self.add_warning("Codelaxy.Core", "src/Codelaxy.Core/A.cs", "CS1002", "error")
        self.flush()
        with self.assertRaisesRegex(GateError, "compiler error"):
            self.run_check()

    def test_f3_11_outside_repository_fails(self):
        self.add_warning("Codelaxy.Core", "src/Codelaxy.Core/A.cs", "CA1234",
                         source_uri="file:///tmp/elsewhere/Evil.cs")
        self.flush()
        with self.assertRaisesRegex(GateError, "outside repository"):
            self.run_check()

    def test_f3_12_duplicate_baseline_key_fails(self):
        content = json.loads(self.baseline.read_text(encoding="utf-8"))
        content["warnings"].append(content["warnings"][0])
        self.baseline.write_text(json.dumps(content), encoding="utf-8")
        with self.assertRaisesRegex(GateError, "Duplicate baseline"):
            self.run_check()

    def test_f3_13_zero_warnings_with_proven_invocation_passes(self):
        for project in PROJECTS:
            self.data[project]["runs"][0]["results"] = []
        self.flush()
        self.run_check()

    def test_f3_14_unknown_severity_fails_closed(self):
        self.data["Codelaxy.Tests"]["runs"][0]["results"][0]["level"] = "mystery"
        self.flush()
        with self.assertRaisesRegex(GateError, "unknown diagnostic level"):
            self.run_check()

    def test_f3_15_no_compiler_rules_fails_closed(self):
        self.data["Codelaxy.Core"]["runs"][0]["tool"]["driver"]["rules"] = []
        self.flush()
        with self.assertRaisesRegex(GateError, "manifest missing"):
            self.run_check()


if __name__ == "__main__":
    unittest.main(verbosity=1)
