"""Independent audit regressions for failure cleanup and bounded execution."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from clxreg import canon, export, pilot
from tests import test_mutation_runner as runner_fixtures
from tests.ledger_forgery import Scenario
from tests.test_export import H, model


class FinalizationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_pilot_malformed_namespace_catalog_is_a_pilot_error(self):
        scene = Scenario(self.root)
        honest = scene.honest()
        for namespace in (None, [], {'namespaces': None}):
            with self.subTest(namespace=namespace), self.assertRaises(pilot.PilotError):
                pilot.build(honest, scene.src, scene.roots, namespace, **scene.pilot_inputs())

    def test_fdopen_failure_closes_descriptor_and_removes_temporary(self):
        descriptors = []

        def fail(fd, mode):
            descriptors.append(fd)
            raise OSError('could not open stream')

        with mock.patch.object(export.os, 'fdopen', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'could not open stream'):
                export.write(self.root / 'view.tsv', model(), registry_commit=H)
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_failed_pilot_write_removes_only_its_new_output(self):
        scene = Scenario(self.root)
        records = pilot.build(scene.honest(), scene.src, scene.roots, scene.ns, **scene.pilot_inputs())
        original = canon.write_record
        written = []

        def fail_second(path, value):
            written.append(path)
            if len(written) == 2:
                raise OSError('disk failed')
            return original(path, value)

        target = self.root / 'candidate'
        with mock.patch.object(canon, 'write_record', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'disk failed'):
                pilot.write(target, records)
        self.assertFalse(target.exists())
        self.assertTrue((scene.ws / 'a.md').exists())

    def test_invalid_library_timeouts_are_rejected_before_work(self):
        runner = runner_fixtures.run_mutants
        for value in (None, True, 0, -1, float('nan'), float('inf'), 'bad'):
            with self.subTest(value=value), mock.patch.object(runner.shutil, 'copytree') as copied:
                with self.assertRaisesRegex(ValueError, 'finite positive'):
                    runner.run(self.root / 'missing.json', timeout=value)
                copied.assert_not_called()
                with self.assertRaisesRegex(ValueError, 'finite positive'):
                    runner._run_tests([], self.root, {}, value)

    def test_invalid_cli_timeout_is_usage_error_without_traceback(self):
        script = Path(__file__).resolve().parents[1] / 'mutation/run_mutants.py'
        for value in ('nan', 'inf', '0', '-1', 'bad'):
            with self.subTest(value=value):
                result = subprocess.run([sys.executable, '-B', str(script), 'missing.json', '--timeout', value], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn('timeout', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
