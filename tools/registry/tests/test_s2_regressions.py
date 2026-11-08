"""Independent audit counterexamples; regression tests for the S2 repair."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

from clxreg import dirty, evidence, freshness, provenance
from tests.test_provenance import good
from tests.test_evidence import evd, req, scn


class AuditRegressions(unittest.TestCase):
    def test_manifest_after_start_in_another_offset_is_not_proven(self):
        f = good()
        f['environment']['utc_offset'] = '+01:00'
        f['manifest_at_run']['captured_at'] = '2026-11-01T15:30:00Z'
        self.assertIn('manifest-at-run', provenance.assess(f).unmet)

    def test_same_instant_different_offsets_and_explicit_naive_clock(self):
        f = good()
        f['environment']['utc_offset'] = '+01:00'
        f['manifest_at_run']['captured_at'] = '2026-11-01T15:09:37Z'
        self.assertNotIn('manifest-at-run', provenance.assess(f).unmet)
        f['environment'].pop('utc_offset')
        f['manifest_at_run']['captured_at'] = '2026-11-01T16:00:00'
        self.assertIn('manifest-at-run', provenance.assess(f).unmet)

    def test_missing_timezone_is_not_an_assumed_instant(self):
        self.assertIsNone(provenance._ts('2026-11-01T16:00:00'))
        self.assertIsNone(provenance._ts('2026-11-01T16:00:00', '+99:00'))

    def test_date_only_or_missing_seconds_is_not_a_capture_timestamp(self):
        for value in ('2026-11-01', '2026-11-01T15:00', '2026-11-01 15:00:00'):
            self.assertIsNone(provenance._ts(value, '+01:00'))

    def test_file_and_directory_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'input'
            root.mkdir()
            external = Path(d) / 'external'
            external.mkdir()
            (external / 'source').write_text('first')
            for target in (external / 'source', external):
                link = root / 'link'
                try:
                    os.symlink(target, link, target_is_directory=target.is_dir())
                except OSError as e:
                    self.skipTest('OS cannot create fixture symlink: ' + str(e))
                with self.assertRaises(dirty.ManifestError):
                    dirty.tree_manifest(root)
                link.unlink()

    def test_nested_git_directory_and_git_link_file_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            nested = root / 'nested'
            nested.mkdir()
            (nested / '.git').write_text('gitdir: elsewhere')
            with self.assertRaises(dirty.ManifestError):
                dirty.tree_manifest(root)

    def test_unreadable_directory_is_not_silently_omitted(self):
        from unittest import mock
        def walk(root, followlinks=False, onerror=None):
            if onerror is not None:
                onerror(PermissionError('fixture unreadable child'))
            return iter(())
        with tempfile.TemporaryDirectory() as d, mock.patch.object(dirty.os, 'walk', walk):
            with self.assertRaises(dirty.ManifestError):
                dirty.tree_manifest(d)

    def test_FR23_type_and_NUL_keep_the_documented_error(self):
        with tempfile.TemporaryDirectory() as d:
            for ref in (17, 'bad\0ref'):
                with self.subTest(ref=repr(ref)), self.assertRaises(freshness.FreshnessError):
                    freshness._resolve(d, ref)

    def test_unknown_persistence_cannot_verify(self):
        for env in ({}, {'freshness': {'E': 'CURRENT'}}):
            d = evidence.derive(req(persistence='TYPO'), {'CLX-SCN-0001': scn()}, {'E': evd()}, env)
            self.assertNotEqual(d.verification, 'VERIFIED')

    def test_repeated_test_observations_cannot_hide_a_failure_by_order(self):
        for outcomes in (('FAIL','PASS'), ('PASS','FAIL'), ('SKIP','PASS'), ('ABSENT','PASS')):
            e=evd(observations=[{'name':'T.One','outcome':v} for v in outcomes])
            result=evidence.derive(req(),{'CLX-SCN-0001':scn()},{'E':e},{})
            self.assertNotEqual(result.verification,'VERIFIED',outcomes)


if __name__ == '__main__':
    unittest.main()
