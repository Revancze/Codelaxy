"""O5: independently observable ledger-shape and Git-base history checks."""
import copy
import unittest
from unittest import mock

from clxreg import canon, ledger, patterns, validator
from tests.test_ledger import Fx
from tests import test_validator as validator_fixtures

R = validator_fixtures.R


class LedgerBoundaryTests(Fx):
    def assert_shape_error(self, value, message):
        for findings in (ledger.validate_ledger(value), ledger.verify_ledger(value, self.src, self.roots)):
            self.assertTrue(any(f.code == 'DE-02' and message in f.message for f in findings), findings)

    def test_source_entry_cannot_describe_a_processed_source(self):
        value = self.build()
        value['entries'][0]['class'] = 'SOURCE'
        self.assert_shape_error(value, 'source entry in processed source')

    def test_ordinary_occurrence_cannot_describe_a_problem_source(self):
        value = self.build()
        value['sources'][0]['status'] = 'PROBLEM'
        value['problems'] = ['doc/v1: changed pinned bytes']
        value['complete'] = False
        self.assert_shape_error(value, 'ordinary entry in nonprocessed source')

    def test_problem_source_does_not_invent_a_source_disposition(self):
        value = self.build()
        value['sources'][0]['status'] = 'PROBLEM'
        value['problems'] = ['doc/v1: changed pinned bytes']
        value['complete'] = False
        entry = copy.deepcopy(value['entries'][0])
        entry['class'] = 'SOURCE'
        value['entries'] = [entry] + [e for e in value['entries'] if e['version'] != 'v1']
        self.assert_shape_error(value, 'PROCESSED or PROBLEM source must not carry a SOURCE entry')

    def test_complete_is_boolean_not_a_truthy_number(self):
        value = self.build()
        value['complete'] = 1
        self.assert_shape_error(value, 'complete contradicts')

    def test_empty_literal_is_rejected_before_source_access(self):
        value = self.build()
        value['entries'][0]['text'] = ''
        with mock.patch('clxreg.sources.read_verified', side_effect=AssertionError('must reject shape first')):
            self.assert_shape_error(value, 'invalid text')

    def test_problems_must_be_an_array_even_when_empty(self):
        value = self.build()
        value['problems'] = ''
        self.assert_shape_error(value, 'problems must be a list')

    def test_contained_column_requires_an_integer(self):
        value = self.build()
        entry = next(e for e in value['entries'] if e.get('contained'))
        entry['contained'][0]['column'] = '1'
        self.assert_shape_error(value, 'invalid contained match')

    def test_unrelated_scanner_value_error_is_not_reclassified(self):
        with mock.patch.object(patterns, 'scan_text', side_effect=ValueError('unrelated scanner failure')):
            with self.assertRaises(ValueError) as caught:
                self.build()
        self.assertIs(type(caught.exception), ValueError)
        self.assertEqual(str(caught.exception), 'unrelated scanner failure')


class GitHistoryBoundaryTests(unittest.TestCase):
    setUp = validator_fixtures.ValidatorTests.setUp
    model = validator_fixtures.ValidatorTests.model
    def test_revision_decrease_has_its_own_diagnostic(self):
        base = copy.deepcopy(self.records)
        digest = canon.normative_digest(base[R])
        base[R]['revision'] = 2
        base[R]['revisions'].append({'n': 2, 'change_class': 'EDITORIAL', 'digest': digest})
        self.records[R]['revisions'] = copy.deepcopy(base[R]['revisions'])
        findings = self.model(base_records=base)['findings']
        self.assertTrue(any(f['code'] == 'DE-08' and f['message'] == 'revision number decreased compared to Git base' for f in findings))
        self.assertFalse(any(f['message'] == 'historical revisions from Git base were removed' for f in findings))

    def test_history_removal_is_diagnosed_without_revision_decrease(self):
        base = copy.deepcopy(self.records)
        digest = canon.normative_digest(base[R])
        base[R]['revision'] = 2
        base[R]['revisions'].append({'n': 2, 'change_class': 'EDITORIAL', 'digest': digest})
        self.records[R]['revision'] = 3
        self.records[R]['revisions'].append({'n': 3, 'change_class': 'EDITORIAL', 'digest': digest})
        findings = self.model(base_records=base)['findings']
        self.assertTrue(any(f['code'] == 'DE-08' and f['message'] == 'historical revisions from Git base were removed' for f in findings))
        self.assertFalse(any(f['message'] == 'revision number decreased compared to Git base' for f in findings))
