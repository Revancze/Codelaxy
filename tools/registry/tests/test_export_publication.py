"""Audit regressions: failed publication and lossless defect metadata."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from clxreg import export
from tests.ledger_forgery import Scenario
from tests.test_export import H, model


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / 'view.tsv'

    def test_partial_write_failure_leaves_no_target_or_temporary(self):
        original = os.fdopen

        class BrokenWriter:
            def __init__(self, fd, mode):
                self.stream = original(fd, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, data):
                self.stream.write(data[:17])
                self.stream.flush()
                raise OSError('simulated full disk')

        with mock.patch.object(export.os, 'fdopen', BrokenWriter):
            with self.assertRaisesRegex(OSError, 'full disk'):
                export.write(self.target, model(), registry_commit=H)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_short_write_is_refused_and_cleaned(self):
        original = os.fdopen

        class ShortWriter:
            def __init__(self, fd, mode):
                self.stream = original(fd, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, data):
                return self.stream.write(data[:17])

        with mock.patch.object(export.os, 'fdopen', ShortWriter):
            with self.assertRaisesRegex(OSError, 'short export write'):
                export.write(self.target, model(), registry_commit=H)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_flush_failure_leaves_no_target_or_temporary(self):
        with mock.patch.object(export.os, 'fsync', side_effect=OSError('flush failed')):
            with self.assertRaisesRegex(OSError, 'flush failed'):
                export.write(self.target, model(), registry_commit=H)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_concurrent_target_is_never_replaced(self):
        original = os.link

        def racing_link(source, target):
            Path(target).write_bytes(b'concurrent owner')
            return original(source, target)

        with mock.patch.object(export.os, 'link', racing_link):
            with self.assertRaises(FileExistsError):
                export.write(self.target, model(), registry_commit=H)
        self.assertEqual(self.target.read_bytes(), b'concurrent owner')
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_unsupported_publication_leaves_no_target_or_temporary(self):
        with mock.patch.object(export.os, 'link', side_effect=OSError('unsupported')):
            with self.assertRaisesRegex(OSError, 'unsupported'):
                export.write(self.target, model(), registry_commit=H)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_complete_exports_preserve_defect_reasons_in_both_modes_and_formats(self):
        scenario = Scenario(self.root)
        (scenario.ws / 'b.md').write_bytes(b'changed\n')
        ledger = scenario.honest()
        for inputs in (None, scenario.export_inputs()):
            tables = export.tables(model(), registry_commit=H, import_ledger=ledger, ledger_inputs=inputs)
            meta = dict(tables['REGISTRY-METADATA'])
            self.assertEqual(json.loads(meta['import_ledger_problem_details']), ledger['problems'])
            detail = json.loads(meta['import_ledger_source_details'])
            self.assertEqual(detail[0]['status'], 'PROBLEM')
            for ext in ('tsv', 'fods'):
                target = self.root / (('verified' if inputs else 'unverified') + '.' + ext)
                export.write(target, model(), registry_commit=H, import_ledger=ledger, ledger_inputs=inputs)
                if ext == 'tsv':
                    text = target.read_text(encoding='utf8')
                else:
                    document = ET.fromstring(target.read_bytes())
                    for spaces in document.iter('{' + export.TEXT + '}s'):
                        spaces.text = ' ' * int(spaces.get('{' + export.TEXT + '}c', '1'))
                    text = ''.join(document.itertext())
                self.assertIn(ledger['problems'][0], text)
        (scenario.ws / 'b.md').unlink()
        missing = scenario.honest()
        details = json.loads(dict(export.tables(model(), registry_commit=H, import_ledger=missing)['REGISTRY-METADATA'])['import_ledger_source_details'])
        self.assertEqual(details[0]['status'], 'MISSING')
        self.assertTrue(details[0]['entries'][0]['reason'])
        self.assertFalse(list(self.root.glob('.*.tmp')))
