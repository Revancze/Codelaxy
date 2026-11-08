"""The same deliberate portable environment has the same precise skip reason."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests import test_sources


class PortableEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_explicit_missing_workspace_precedes_absent_local_catalogs(self):
        missing = self.root / 'no-workspace'
        with mock.patch.object(test_sources, 'LOCAL', self.root / 'no-catalogs'), mock.patch.dict(os.environ, {'CLX_WORKSPACE_ROOT': str(missing)}):
            reason = test_sources._real_skip_reason()
        self.assertIn('is not a directory on this machine', reason)
        self.assertIn(repr(str(missing)), reason)

    def test_existing_workspace_still_reports_absent_local_manifest(self):
        with mock.patch.object(test_sources, 'LOCAL', self.root / 'no-catalogs'), mock.patch.dict(os.environ, {'CLX_WORKSPACE_ROOT': str(self.root)}):
            reason = test_sources._real_skip_reason()
        self.assertIn('protected-manifest.json', reason)
        self.assertIn('is not present', reason)

    def test_no_workspace_override_keeps_the_machine_local_diagnostic(self):
        with mock.patch.object(test_sources, 'LOCAL', self.root / 'no-catalogs'), mock.patch.dict(os.environ, {'CLX_WORKSPACE_ROOT': ''}):
            reason = test_sources._real_skip_reason()
        self.assertIn('machine-local, not part of any patch', reason)
