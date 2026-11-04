"""Actual-source pilot remains UNKNOWN; ranges and ambiguity are not resolved."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from clxreg import canon, pilot, validator, ledger, namespaces

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
    def build(self): return pilot.build(self.ledger,self.catalog,self.roots,self.namespaces)
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
                self.assertRaises((pilot.PilotError,ValueError),pilot.build,obj,self.catalog,self.roots,self.namespaces)
    def test_no_mapping_from_ambiguous_or_missing_namespace(self):
        self.namespaces['namespaces']=[n for n in self.namespaces['namespaces'] if n['key']!='micromap-resolver-gaps']
        self.assertRaises(pilot.PilotError,self.build)
    def test_incomplete_ledger_is_never_used_for_a_pilot(self):
        self.ledger['complete']=False
        self.assertRaises(pilot.PilotError,self.build)
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
        run={'schema':ledger.RUN_SCHEMA,'include':[{'source':'doc','version':'ratified-bytes'}],'excluded':[]}
        self.ledger=ledger.build_ledger(run,self.catalog,self.namespaces,None,{'schema':ledger.MAPPING_SCHEMA,'tokens':{}},self.roots)
    def test_rt2_cannot_be_activated_and_mutant_evidence_cannot_bind(self):
        records=self.build();records['CLX-REQ-0002']['aliases'][0]['status']='ACTIVE'
        m=validator.validate(records,source_catalog=self.catalog,namespace_catalog=self.namespaces,source_roots=self.roots)
        self.assertTrue(any(f['class']=='DATA_ERROR' for f in m['findings']))
        from tests.test_validator import complete_records
        scn=complete_records()['CLX-SCN-0001'];scn['verifies'][0]['basis']={'source':'doc','version':'ratified-bytes','quote':'RT1'}
        records=self.build();records[scn['id']]=scn
        self.assertIn('DE-15',{f['code'] for f in validator.validate(records,source_catalog=self.catalog,source_roots=self.roots)['findings']})

if __name__=='__main__': unittest.main()
