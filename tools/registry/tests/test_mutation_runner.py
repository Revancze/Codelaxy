"""The mutation runner is bounded: a hanging test run cannot block it forever."""
import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location('run_mutants_under_test', ROOT / 'mutation' / 'run_mutants.py')
run_mutants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_mutants)

PASSED = subprocess.CompletedProcess([], 0, '', '')
MUTANT = {'id': 'T1', 'file': 'clxreg/pilot.py', 'old': 'class PilotError(ValueError):', 'new': 'class PilotError(ValueError): # mutated', 'note': 'hangs'}


class TimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.spec = self.d / 'spec.json'
        self.spec.write_text(json.dumps({'tests': ['tests.test_nothing'], 'mutants': [MUTANT]}), encoding='utf-8')

    def execute(self, outcomes):
        report = self.d / 'report.json'
        with mock.patch.object(run_mutants, '_run_tests', side_effect=outcomes) as patched, redirect_stdout(io.StringIO()):
            code = run_mutants.run(self.spec, report, timeout=7)
        self.assertTrue(all(call.args[3] == 7 for call in patched.call_args_list))
        return code, report

    def test_a_hanging_process_is_killed_at_the_limit(self):
        started = time.monotonic()
        result = run_mutants._run_tests([sys.executable, '-c', 'import time; time.sleep(60)'], self.d, dict(os.environ), 0.5)
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - started, 30)

    def test_a_finished_process_is_returned(self):
        result = run_mutants._run_tests([sys.executable, '-c', 'raise SystemExit(3)'], self.d, dict(os.environ), 30)
        self.assertEqual(result.returncode, 3)

    def test_a_hanging_mutant_is_reported_and_the_run_finishes(self):
        code, report = self.execute([PASSED, None])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['results'], [{'id': 'T1', 'status': 'KILLED-TIMEOUT'}])

    def test_a_hanging_baseline_makes_the_result_meaningless(self):
        self.assertEqual(self.execute([None])[0], 2)


if __name__ == '__main__':
    unittest.main()
