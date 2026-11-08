"""Regressions for the three follow-up PR review findings."""
import copy
import subprocess
import sys
import unittest

from clxreg import canon, evidence, export, validator
from tests import test_evidence as evidence_fixtures
from tests import test_validator as validator_fixtures
from tests.test_export import H


class ReviewFollowupTests(unittest.TestCase):
    setUp = validator_fixtures.ValidatorTests.setUp
    model = validator_fixtures.ValidatorTests.model

    def test_accepted_adequacy_cannot_be_borrowed_from_a_normative_old_revision(self):
        e = evidence_fixtures.evd(evidences=[{'requirement': evidence_fixtures.REQ, 'requirement_revision': 2, 'acceptance': 'AC-1'}])
        s = evidence_fixtures.scn()
        s['verifies'].append({**s['verifies'][0], 'requirement_revision': 2, 'adequacy': 'ASSERTED'})
        ctx = evidence_fixtures.QualifyTests().ctx(revisions=(2,))
        result = evidence.qualify(e, s, ctx)
        self.assertFalse(result.qualifies)
        self.assertTrue(any(f.startswith('Q5:') for f in result.failed))

    def test_missing_revision_is_not_an_accepted_binding(self):
        scenario = evidence_fixtures.scn()
        scenario['verifies'][0].pop('requirement_revision')
        result = evidence.qualify(evidence_fixtures.evd(), scenario, evidence_fixtures.QualifyTests().ctx())
        self.assertFalse(result.qualifies)
        self.assertTrue(any(f.startswith('Q5:') for f in result.failed))

    def test_explicit_editorial_equivalence_preserves_accepted_adequacy(self):
        e = evidence_fixtures.evd(evidences=[{'requirement': evidence_fixtures.REQ, 'requirement_revision': 2, 'acceptance': 'AC-1'}])
        result = evidence.qualify(e, evidence_fixtures.scn(), evidence_fixtures.QualifyTests().ctx(revisions=(1, 2)))
        self.assertTrue(result.qualifies, result.failed)

    def test_normative_refinement_needs_new_accepted_scenario_binding(self):
        R, S, E = validator_fixtures.R, validator_fixtures.S, validator_fixtures.E
        base = copy.deepcopy(self.records)
        self.records[R]['statement'] = 'A refined normative obligation'
        self.records[R]['revision'] = 2
        self.records[R]['revisions'].append({'n': 2, 'change_class': 'REFINEMENT', 'digest': canon.normative_digest(self.records[R])})
        self.records[S]['verifies'].append({**self.records[S]['verifies'][0], 'requirement_revision': 2, 'adequacy': 'ASSERTED'})
        self.records[S]['revision'] = 2
        self.records[S]['revisions'].append({'n': 2, 'change_class': 'REFINEMENT', 'digest': canon.normative_digest(self.records[S])})
        self.records[E]['scenario_revision'] = 2
        self.records[E]['evidences'][0]['requirement_revision'] = 2
        new_evidence = self.records.pop(E)
        new_evidence['id'] = 'CLX-EVD-0002'
        self.records['CLX-EVD-0002'] = new_evidence
        self.records[E] = copy.deepcopy(base[E])
        decisions = [{'id': rid, 'status': 'ACCEPTED', 'authority': 'owner-message-recorded', 'decision_kind': 'revision', 'decided_by': {'role': 'owner'}, 'decided_on': '2026-11-08', 'source': copy.deepcopy(validator_fixtures.REF), 'concerns': [{'record': rid, 'effect': 'revised', 'revision': 2}]} for rid in (R, S)]
        model = self.model(base_records=base, context={'decisions': decisions})
        self.assertTrue(model['valid'], model['findings'])
        self.assertNotEqual(model['derived'][R]['verification'], 'VERIFIED')
        self.assertFalse(validator.gate(model, R)['passed'])
        self.records[S]['verifies'][-1]['adequacy'] = 'ACCEPTED'
        self.records[S]['revisions'][-1]['digest'] = canon.normative_digest(self.records[S])
        model = self.model(base_records=base, context={'decisions': decisions})
        self.assertTrue(model['valid'], model['findings'])
        self.assertTrue(validator.gate(model, R)['passed'], model['findings'])

    def test_overlapping_acyclic_graph_is_bounded(self):
        script = '''
from clxreg import validator
records={str(n):{'depends_on':[str(x) for x in (n+1,n+2) if x<90]} for n in range(90)}
run=validator.Run(records,None,None,{},None,{},1)
validator._references(run)
assert not run.findings, run.findings
'''
        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_completed_graphs_do_not_hide_real_cycles(self):
        records = {'a': {'depends_on': ['b']}, 'b': {'depends_on': ['c']}, 'c': {'depends_on': ['b']}, 'd': {'depends_on': ['b']}}
        run = validator.Run(records, None, None, {}, None, {}, 1)
        validator._references(run)
        self.assertTrue(any(f.code == 'DE-04' and 'cycle in depends_on' in f.message for f in run.findings))

    def test_verification_claims_use_verification_and_done_claims_use_effective_status(self):
        R = validator_fixtures.R
        for claimed, expected_drift in (('VERIFIED', ''), ('DONE', ''), ('PARTIAL', 'CLAIM_DIFFERS')):
            records = copy.deepcopy(self.records)
            records[R]['asserted_status'] = [{'status': claimed, 'as_of': '2026-11-08', 'source': copy.deepcopy(validator_fixtures.REF)}]
            model = self.model(records)
            self.assertTrue(model['valid'], model['findings'])
            tables = export.tables(model, registry_commit=H)
            row = next(row for row in tables['REGISTRY-ROADMAP'][1:] if row[0] == R)
            self.assertEqual(row[3:5], ['VERIFIED', 'DONE'])
            self.assertEqual(row[6], expected_drift)
            for serializer in (export.tsv, export.fods):
                data = serializer(tables)
                self.assertEqual(b'CLAIM_DIFFERS' in data, bool(expected_drift))
