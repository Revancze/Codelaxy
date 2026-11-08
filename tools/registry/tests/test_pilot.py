"""Actual-source pilot remains UNKNOWN; ranges and ambiguity are not resolved."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from clxreg import canon, pilot, validator, ledger, namespaces
from tests import ledger_forgery as forge

ROOT=Path(__file__).resolve().parent.parent
LOCAL=ROOT/'local'
WORKSPACE=Path(os.environ.get('CLX_WORKSPACE_ROOT',r'C:\Users\AnubW\Documents\Projects\CodelaxyWorkspace'))
LEDGER=WORKSPACE/'proposals/traceability-architecture/phase2/s1/real-run/ledger-micromap-1.json'

class PilotTests(unittest.TestCase):
    def setUp(self):
        if not LEDGER.is_file() or not (LOCAL/'sources.json').is_file(): self.skipTest('actual source ledger/local catalog not available')
        self.ledger=json.loads(LEDGER.read_text(encoding='utf-8'))
        self.catalog=json.loads((LOCAL/'sources.json').read_text(encoding='utf-8'))
        self.namespaces=json.loads((ROOT/'catalog-specs/namespaces.micromap.json').read_text(encoding='utf-8'))
        self.roots={'workspace':str(WORKSPACE)}
        self.run=json.loads((ROOT/'catalog-specs/run.micromap.json').read_text(encoding='utf-8'))
        self.ambiguity=json.loads((ROOT/'catalog-specs/ambiguity.micromap.json').read_text(encoding='utf-8'))
        self.mapping=None
    def trusted(self): return {'run':self.run,'ambiguity':self.ambiguity,'mapping':self.mapping}
    def build(self): return pilot.build(self.ledger,self.catalog,self.roots,self.namespaces,**self.trusted())
    def test_real_pilot_is_unknown_and_does_not_claim_a_definition(self):
        records=self.build()
        self.assertEqual(len(records),3)
        m=validator.validate(records,source_catalog=self.catalog,namespace_catalog=self.namespaces,source_roots=self.roots)
        self.assertTrue(m['valid'],m['findings'])
        self.assertEqual({d['verification'] for d in m['derived'].values()},{'UNKNOWN'})
        self.assertFalse(validator.gate(m)['passed'])
        self.assertEqual(records['CLX-REQ-0002']['aliases'][0]['status'],'IMPLIED_BY_RANGE')
        for r in records.values():
            self.assertEqual(r['definition'],'UNRESOLVED');self.assertFalse(r['acceptance'][0]['resolved']);self.assertEqual(r['ms_ref'],'M3d')
            self.assertNotIn('assigned_to',r);self.assertNotIn('DEC',r['type']);self.assertIn('TD-9',r['note'])
    def test_ledger_location_or_identity_tampering_is_refused(self):
        for field,value in (('sha256','0'*64),('line',999999),('column',9999)):
            obj=copy.deepcopy(self.ledger)
            for e in obj['entries']:
                if e.get('text')=='RT1' and e.get('namespace')=='micromap-resolver-gaps': e[field]=value
            with self.subTest(field=field):
                self.assertRaises((pilot.PilotError,ValueError),pilot.build,obj,self.catalog,self.roots,self.namespaces,**self.trusted())
    def test_no_mapping_from_ambiguous_or_missing_namespace(self):
        self.namespaces['namespaces']=[n for n in self.namespaces['namespaces'] if n['key']!='micromap-resolver-gaps']
        self.assertRaisesRegex(pilot.PilotError,'no namespace is invented',self.build)
    def test_incomplete_ledger_is_never_used_for_a_pilot(self):
        self.ledger['complete']=False
        self.assertRaisesRegex(pilot.PilotError,'complete valid ledger',self.build)
    def test_pilot_reproducible_and_write_is_exclusive(self):
        a=self.build();b=self.build();self.assertEqual(a,b)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'pilot';pilot.write(out,a)
            before={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*.json')}
            self.assertEqual(len(before),3)
            self.assertRaises(pilot.PilotError,pilot.write,out,b)
            self.assertEqual(before,{p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*.json')})
    def test_rt2_cannot_be_activated_and_mutant_evidence_cannot_bind(self):
        records=self.build();records['CLX-REQ-0002']['aliases'][0]['status']='ACTIVE'
        m=validator.validate(records,source_catalog=self.catalog,namespace_catalog=self.namespaces,source_roots=self.roots)
        self.assertTrue(any(f['class']=='DATA_ERROR' for f in m['findings']))
        from tests.test_validator import complete_records
        scn=complete_records()['CLX-SCN-0001'];scn['verifies'][0]['basis']={'source':'micromap','version':'ratified-bytes','quote':'RT1'}
        records=self.build();records[scn['id']]=scn
        self.assertIn('DE-15',{f['code'] for f in validator.validate(records,source_catalog=self.catalog,source_roots=self.roots)['findings']})

class SyntheticPilotTests(PilotTests):
    """The same safety cases also run without machine-local sources in mutations."""
    def setUp(self):
        from tests.test_sources import good_catalog, FILES
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for name,data in FILES.items(): (root/name).write_bytes(data)
        data='RT1 and RT3.\nGate RT1–RT3 killed.\n'.encode('utf-8')
        (root/'v2.md').write_bytes(data)
        self.catalog=good_catalog()
        document=next(s for s in self.catalog['sources'] if s['key']=='doc')
        version=next(v for v in document['versions'] if v['id']=='v2')
        version.update(id='ratified-bytes',sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
        document['versions']=[version]
        self.roots={'ws':str(root)}
        self.namespaces={'schema':namespaces.SCHEMA,'namespaces':[{'key':'micromap-resolver-gaps','label_pattern':'RT[1-3]','meaning':'resolver labels only; definitions absent','authority':{'source':'doc','version':'ratified-bytes','quote':'RT1 and RT3.'},'status':'LIVE','maps_to':'EXTERNAL','distinct_from':[]}]}
        self.run={'schema':ledger.RUN_SCHEMA,'include':[{'source':'doc','version':'ratified-bytes'}],'excluded':[]}
        self.ambiguity=None
        self.mapping={'schema':ledger.MAPPING_SCHEMA,'tokens':{}}
        self.ledger=ledger.build_ledger(self.run,self.catalog,self.namespaces,self.ambiguity,self.mapping,self.roots)
    def test_location_recheck_still_holds_if_the_rebuild_is_stubbed(self):
        # Second layer: the selected occurrences are rechecked against pinned bytes on their own.
        for field,value in (('sha256','0'*64),('line',999999),('column',9999)):
            obj=copy.deepcopy(self.ledger)
            for e in obj['entries']:
                if e.get('text')=='RT1' and e.get('namespace')=='micromap-resolver-gaps': e[field]=value
            with self.subTest(field=field),mock.patch.object(ledger,'require_rebuild_match'):
                self.assertRaises(pilot.PilotError,pilot.build,obj,self.catalog,self.roots,self.namespaces,**self.trusted())
    def test_rt2_cannot_be_activated_and_mutant_evidence_cannot_bind(self):
        records=self.build();records['CLX-REQ-0002']['aliases'][0]['status']='ACTIVE'
        m=validator.validate(records,source_catalog=self.catalog,namespace_catalog=self.namespaces,source_roots=self.roots)
        self.assertTrue(any(f['class']=='DATA_ERROR' for f in m['findings']))
        from tests.test_validator import complete_records
        scn=complete_records()['CLX-SCN-0001'];scn['verifies'][0]['basis']={'source':'doc','version':'ratified-bytes','quote':'RT1'}
        records=self.build();records[scn['id']]=scn
        self.assertIn('DE-15',{f['code'] for f in validator.validate(records,source_catalog=self.catalog,source_roots=self.roots)['findings']})

class PilotTrustBoundaryTests(unittest.TestCase):
    """A structurally valid forged ledger cannot produce a pilot decision."""
    # (name, second source, trusted ambiguity, forgery): each flips an honest refusal.
    FLIPPING=(('K1',forge.WITH_RT2,None,forge.k1_processed_to_excluded),
              ('K2',forge.WITH_RT2,None,forge.k2_drop_rt2),
              ('K6',forge.CLEAN,forge.AMBIGUOUS_RT1,forge.k6_erase_ambiguity),
              ('K7',forge.WITH_RT2,None,forge.k7_omit_source))
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.count=0
    def scenario(self,second=forge.CLEAN,ambiguity=None,mapping=None):
        self.count+=1
        directory=Path(self.tmp.name)/str(self.count);directory.mkdir()
        return forge.Scenario(directory,second,ambiguity,mapping)
    def build(self,s,led,**kw):
        return pilot.build(copy.deepcopy(led),s.src,s.roots,s.ns,**{**s.pilot_inputs(),**kw})
    def test_honest_ledger_with_its_trusted_inputs_is_accepted(self):
        s=self.scenario();records=self.build(s,s.honest())
        self.assertEqual(sorted(records),['CLX-REQ-0001','CLX-REQ-0002','CLX-REQ-0003'])
        with mock.patch.object(ledger,'require_rebuild_match'):
            self.assertEqual(records,self.build(s,s.honest()))
    def test_honest_refusals_stay_refusals(self):
        s=self.scenario(forge.WITH_RT2)
        self.assertRaisesRegex(pilot.PilotError,'RT2 literal occurrence',self.build,s,s.honest())
        s=self.scenario(ambiguity=forge.AMBIGUOUS_RT1)
        self.assertRaisesRegex(pilot.PilotError,'no unambiguous literal',self.build,s,s.honest())
    def test_honest_incomplete_ledger_is_refused_even_with_trusted_inputs(self):
        s=self.scenario();(s.ws/'b.md').unlink();led=s.honest()
        self.assertFalse(led['complete'])
        self.assertRaisesRegex(pilot.PilotError,'complete valid ledger',self.build,s,led)
    def test_trusted_inputs_cannot_be_left_out(self):
        s=self.scenario();led=s.honest()
        self.assertRaisesRegex(pilot.PilotError,'trusted run',pilot.build,led,s.src,s.roots,s.ns)
        self.assertRaisesRegex(pilot.PilotError,'trusted run',self.build,s,led,run=None)
        self.assertRaisesRegex(pilot.PilotError,'explicit trusted',pilot.build,led,s.src,s.roots,s.ns,run=s.run,mapping=None)
        self.assertRaisesRegex(pilot.PilotError,'explicit trusted',pilot.build,led,s.src,s.roots,s.ns,run=s.run,ambiguity=None)
    def test_forgeries_are_structurally_clean_and_would_flip_the_decision(self):
        for name,second,ambiguity,forgery in self.FLIPPING:
            s=self.scenario(second,ambiguity);honest=s.honest();forged=forgery(honest)
            with self.subTest(name):
                self.assertTrue(forged['complete'])
                self.assertEqual(ledger.validate_ledger(forged),[])
                self.assertEqual(ledger.verify_ledger(forged,s.src,s.roots),[])
                with mock.patch.object(ledger,'require_rebuild_match'):
                    self.assertRaises(pilot.PilotError,self.build,s,honest)
                    self.assertEqual(len(self.build(s,forged)),3)
    def test_forgeries_are_refused_by_the_rebuild(self):
        for name,second,ambiguity,forgery in self.FLIPPING:
            s=self.scenario(second,ambiguity);forged=forgery(s.honest())
            with self.subTest(name):
                self.assertRaisesRegex(pilot.PilotError,'not the import of the trusted inputs',self.build,s,forged)
    def test_fabricated_disposition_is_refused_though_it_cannot_change_the_records(self):
        s=self.scenario();honest=s.honest();forged=forge.k5_fabricated_alias(honest)
        self.assertEqual(ledger.validate_ledger(forged),[])
        with mock.patch.object(ledger,'require_rebuild_match'):
            self.assertEqual(self.build(s,forged),self.build(s,honest))
        self.assertRaisesRegex(pilot.PilotError,'not the import of the trusted inputs',self.build,s,forged)
    def test_ambiguity_and_mapping_are_trusted_inputs_and_stored_digests_prove_nothing(self):
        s=self.scenario(ambiguity=forge.AMBIGUOUS_RT1)
        built_without=ledger.build_ledger(s.run,s.src,s.ns,None,None,s.roots)
        self.assertRaisesRegex(pilot.PilotError,'not the import',self.build,s,built_without)
        claiming=copy.deepcopy(built_without);claiming['inputs']=s.honest()['inputs']
        self.assertEqual(ledger.validate_ledger(claiming),[])
        self.assertRaisesRegex(pilot.PilotError,'not the import',self.build,s,claiming)
        s=self.scenario(mapping={'schema':ledger.MAPPING_SCHEMA,'tokens':{}})
        self.assertEqual(len(self.build(s,s.honest())),3)
        self.assertRaisesRegex(pilot.PilotError,'not the import',self.build,s,s.honest(),mapping=None)
    def test_unusable_inputs_are_refused_without_claiming_forgery(self):
        s=self.scenario();led=s.honest()
        self.assertRaisesRegex(pilot.PilotError,'cannot be verified',self.build,s,led,run={'schema':'bad'})
        (s.ws/'b.md').unlink()
        self.assertRaisesRegex(pilot.PilotError,'cannot be verified',self.build,s,led)

if __name__=='__main__': unittest.main()
