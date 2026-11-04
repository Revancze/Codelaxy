"""S3 behavior tests: malformed data never becomes a successful gate."""
import copy
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from clxreg import canon, validator as v, evidence
from clxreg import namespaces
from tests.test_sources import FILES, good_catalog
from tests.test_evidence import evd, scn, req

R='CLX-REQ-0001'; S='CLX-SCN-0001'; E='CLX-EVD-0001'
REF={'source':'doc','version':'v2','anchor':'L2','quote':'RT1–RT3 are the resolver test gaps.'}

def complete_records():
    r=req(schema_version=1,type='REQ',title='A requirement',kind='test-obligation',statement='A condition',statement_origin='quoted',lifecycle='ACTIVE',origin=copy.deepcopy(REF),ratification={'state':'DRAFT'},revisions=[])
    r['applies_to']={'platforms':['windows']}
    r['acceptance'][0]['text']='Observable acceptance'
    s=scn(schema_version=1,id=S,type='SCN',title='A scenario',lifecycle='ACTIVE',definition='DEFINED',procedure='Execute the test',procedure_origin='authored',expected='PASS',platforms_required=['windows'],revisions=[])
    s['verifies'][0].update(requirement_revision=1,basis=copy.deepcopy(REF))
    s['implementation'][0].update(path='tests/Test.cs',commit='227733484a1851bc512f7ba3fef6dd78b6d0e5da')
    e=evd(schema_version=1,id=E,type='EVD',title='A result')
    e['artifacts']=[{'role':'test-log','locator':'artifact.txt','sha256':hashlib.sha256(b'PASS\n').hexdigest()}]
    e['platform']['os']='windows'
    for o in (r,s): o['revisions']=[{'n':1,'change_class':'INITIAL','digest':canon.normative_digest(o)}]
    return {R:r,S:s,E:e}

def digest(records):
    for r in records.values():
        if r.get('type') in ('REQ','SCN') and r.get('revisions'):
            r['revisions'][-1]['digest']=canon.normative_digest(r)

class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name,data in FILES.items(): (self.root/name).write_bytes(data)
        (self.root/'artifact.txt').write_bytes(b'PASS\n')
        self.records=complete_records();self.cat=good_catalog()
    def model(self,records=None,**kw):
        kw['context']={'artifact_root':str(self.root),**kw.get('context',{})}
        return v.validate(self.records if records is None else records,source_catalog=self.cat,source_roots={'ws':str(self.root)},**kw)
    def codes(self,m): return {f['code'] for f in m['findings']}
    def git_currency(self,records,*,changed=False,unrelated=False):
        from tests.test_store import git,commit_all
        tmp=tempfile.TemporaryDirectory(dir=self.root);self.addCleanup(tmp.cleanup)
        repo=Path(tmp.name);git(repo,'init','-q');(repo/'src').mkdir();(repo/'src/Test.cs').write_text('base')
        commit_all(repo,'base currency');base=git(repo,'rev-parse','HEAD').stdout.strip()
        records[E]['subject']['commit']=base;records[S]['scope_paths']=['src/**'];records[S]['implementation'][0]['commit']=base
        if changed:
            (repo/'src/Test.cs').write_text('changed');commit_all(repo,'changed measured scope')
        if unrelated:
            (repo/'notes.txt').write_text('unrelated');commit_all(repo,'unrelated change')
        return {'repo':str(repo),'ref':'HEAD'}
    def test_complete_evidence_can_verify_and_gate(self):
        m=self.model();self.assertTrue(m['valid'],m['findings']);self.assertEqual(m['derived'][R]['effective_status'],'DONE');self.assertTrue(v.gate(m,R)['passed'])
    def test_external_findings_never_change_verdict(self):
        a=self.model();b=self.model(context={'external_findings':[{'class':'DATA_ERROR','code':'DE-02'}]})
        self.assertEqual(a,b)
    def test_empty_or_unselected_gate_never_passes(self):
        m=self.model({});self.assertIn('DE-00',self.codes(m));self.assertFalse(v.gate(m)['passed']);self.assertFalse(v.gate(self.model(),'missing')['passed'])
        self.assertRaises(ValueError,lambda:self.model(min_records=0))
    def test_unknown_policy_and_derived_field_cannot_verify(self):
        self.records[R]['persistence']='TYPO';self.records[R]['verification']='VERIFIED'
        m=self.model();self.assertTrue({'DE-02','DE-11'}<=self.codes(m));self.assertFalse(v.gate(m)['passed'])
    def test_data_errors_cannot_leave_a_positive_derived_claim(self):
        self.records[R]['verification']='VERIFIED'
        m=self.model();self.assertEqual(m['derived'][R]['verification'],'UNKNOWN');self.assertFalse(v.gate(m)['passed'])
    def test_gate_rechecks_blocking_findings_even_on_a_supplied_model(self):
        m=self.model();m['findings'].append({'class':'DATA_ERROR','code':'DE-02','record':R,'message':'bad supplied model'})
        self.assertFalse(v.gate(m)['passed'])
    def test_missing_baseline_reference_is_named_as_unknown_reference(self):
        self.records[E]['baseline']='CLX-EVD-9999'
        self.assertIn('DE-03',self.codes(self.model()))
    def test_no_silent_drop_of_malformed_records(self):
        for bad in ({R:None},{R:[]},{R:'bad'}):
            self.assertTrue({'DE-00','DE-02'}<=self.codes(self.model(bad)))
    def test_cycle_is_rejected(self):
        self.records[R]['depends_on']=[{'target':R}]
        self.assertIn('DE-04',self.codes(self.model()))
    def test_revision_and_pinned_quote_cannot_be_forged(self):
        base=copy.deepcopy(self.records);self.records[R]['statement']='changed';self.records[R]['origin']['quote']='not present'
        m=self.model(base_records=base);self.assertTrue({'DE-08','DE-08b','DE-13'}<=self.codes(m))
    def test_source_unavailability_does_not_manufacture_accepted_adequacy(self):
        (self.root/'v2.md').unlink();m=self.model()
        self.assertTrue({'AD-04','DE-14'}<=self.codes(m));self.assertFalse(v.gate(m)['passed'])
    def test_unresolved_binding_is_a_data_error(self):
        self.records[R].update(definition='UNRESOLVED',definition_note='Definition absent')
        digest(self.records);m=self.model();self.assertIn('DE-15',self.codes(m));self.assertEqual(m['derived'][R]['verification'],'UNKNOWN')
    def test_decision_only_never_verifies_and_missing_decision_prevents_done(self):
        self.records[R]['acceptance'].append({'id':'AC-2','text':'Owner acceptance','kind':'decision','resolved':True,'requires':{'decision_kind':'acceptance'}})
        digest(self.records);m=self.model();self.assertEqual(m['derived'][R]['verification'],'VERIFIED');self.assertEqual(m['derived'][R]['effective_status'],'PARTIAL');self.assertIn('EM-11',self.codes(m));self.assertFalse(v.gate(m)['passed'])
        self.records[R]['acceptance']=self.records[R]['acceptance'][1:];self.records.pop(S);self.records.pop(E);digest(self.records)
        self.assertEqual(self.model()['derived'][R]['verification'],'UNVERIFIED')
    def test_documented_decision_is_rechecked_not_trusted_by_id(self):
        self.records[R]['acceptance'].append({'id':'AC-2','text':'Owner accepts','kind':'decision','resolved':True,'requires':{'decision_kind':'acceptance'}});digest(self.records)
        decision={'id':'accept','status':'ACCEPTED','authority':'owner-message-recorded','decision_kind':'acceptance','decided_by':{'role':'owner'},'decided_on':'2026-11-02','source':copy.deepcopy(REF),'concerns':[{'record':R}]}
        m=self.model(context={'decisions':[decision]});self.assertEqual(m['derived'][R]['effective_status'],'DONE')
        decision['source']['quote']='false';self.assertEqual(self.model(context={'decisions':[decision]})['derived'][R]['effective_status'],'PARTIAL')
    def test_requirement_dependency_waits_for_done_and_detects_cycle(self):
        r2=copy.deepcopy(self.records[R]);r2.update(id='CLX-REQ-0002',origin={**REF,'fragment':'second'});r2['acceptance']=[{'id':'AC-1','text':'First requirement done','kind':'requirement','resolved':True,'requires':{'requirements':[R]}}];self.records[r2['id']]=r2;digest(self.records)
        self.assertEqual(self.model()['derived'][r2['id']]['effective_status'],'DONE')
        self.records[R]['acceptance']=[{'id':'AC-1','text':'Second requirement done','kind':'requirement','resolved':True,'requires':{'requirements':[r2['id']]}}];digest(self.records)
        self.assertIn('DE-04',self.codes(self.model()))
    def test_declared_status_drift_blocks_gate(self):
        self.records[E]['result']='INCONCLUSIVE';self.records[R]['asserted_status']=[{'status':'DONE','source':REF}]
        m=self.model();self.assertIn('EM-06',self.codes(m));self.assertFalse(v.gate(m)['passed'])
    def test_retired_blocked_and_stale_are_not_done(self):
        self.records[R]['blocked']={'by':[R],'note':'waiting'}
        self.assertEqual(self.model()['derived'][R]['effective_status'],'BLOCKED')
        self.records[R].pop('blocked');self.records[R]['persistence']='CONTINUOUS'
        m=self.model(context=self.git_currency(self.records,changed=True));self.assertEqual(m['derived'][R]['effective_status'],'UNKNOWN');self.assertIn('EM-03',self.codes(m))
    def test_current_from_context_is_not_git_proof(self):
        for persistence in ('CONTINUOUS','UNSPECIFIED'):
            rs=complete_records();rs[R]['persistence']=persistence
            rs[E]['subject']['commit']='f'*40
            for context in ({},{'freshness':{E:'CURRENT'}}):
                with self.subTest(persistence=persistence,context=context):
                    m=self.model(rs,context=context)
                    self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED')
                    self.assertFalse(v.gate(m)['passed'])
    def test_live_git_currency_overrides_supplied_claims_in_both_directions(self):
        for changed,unrelated in ((False,False),(False,True),(True,False)):
            rs=complete_records();rs[R]['persistence']='CONTINUOUS'
            context=self.git_currency(rs,changed=changed,unrelated=unrelated)
            context['freshness']={E:'CURRENT' if changed else 'STALE'}
            m=self.model(rs,context=context)
            self.assertEqual(v.gate(m)['passed'],not changed,m['findings'])
            self.assertEqual(m['derived'][R]['verification'],'STALE' if changed else 'VERIFIED')
    def test_unavailable_git_unknown_commit_and_invalid_ref_cannot_be_overridden(self):
        rs=complete_records();rs[R]['persistence']='CONTINUOUS'
        measured=self.git_currency(rs)
        cases=[{**measured,'repo':str(self.root/'missing-repository')},
               {**measured,'ref':'not-a-real-ref'}]
        unknown=copy.deepcopy(rs);unknown[E]['subject']['commit']='f'*40
        cases.append(measured)
        for i,context in enumerate(cases):
            context={**context,'freshness':{E:'CURRENT'}}
            m=self.model(unknown if i==2 else rs,context=context)
            self.assertFalse(v.gate(m)['passed'])
            self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED')
            self.assertIn('AD-09',self.codes(m))
    def test_withdrawn_scenario_and_missing_mutation_baseline_cannot_verify(self):
        self.records[S]['lifecycle']='WITHDRAWN';m=self.model();self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED')
        self.records=complete_records();self.records[S].update(method='mutation',mutant={'target':'x','description':'disable','baseline_required':True});self.records[E]['baseline']='CLX-EVD-9999';digest(self.records)
        m=self.model();self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED');self.assertIn('EM-07',self.codes(m))
        self.records=complete_records();self.records[S]['lifecycle']='PROPOSED'
        self.assertNotEqual(self.model()['derived'][R]['verification'],'VERIFIED')
    def test_alias_deletion_and_evidence_rewriting_are_caught_against_base(self):
        base=copy.deepcopy(self.records);base[R]['aliases']=[{'namespace':'n','value':'RT1','status':'ACTIVE','source':REF}]
        self.assertIn('DE-06',self.codes(self.model(base_records=base)))
        base=copy.deepcopy(self.records);self.records[E]['result']='FAIL'
        self.assertIn('DE-06',self.codes(self.model(base_records=base)))
    def test_input_immutable_deterministic_and_json_serializable(self):
        old=copy.deepcopy(self.records);a=self.model();b=self.model(dict(reversed(list(self.records.items()))));self.assertEqual(a,b);self.assertEqual(old,self.records);json.dumps(a)
    def test_schema_matches_structural_field_catalog(self):
        schema=json.loads(v.SCHEMA_PATH.read_text());self.assertEqual({x['properties']['type']['const'] for x in schema['oneOf']},set(v.FIELDS))
        for x in schema['oneOf']:
            typ=x['properties']['type']['const'];self.assertEqual(set(x['properties']),v.FIELDS[typ]);self.assertFalse(x['additionalProperties'])
    def test_unknown_nested_fields_types_and_enums_fail_closed(self):
        cases=[
          lambda rs:rs[R]['acceptance'][0].update(kind='TYPO'),
          lambda rs:rs[R]['acceptance'][0].update(requires={'independence':'TYPO'}),
          lambda rs:rs[R]['acceptance'][0].update(requires={'platforms':[]}),
          lambda rs:rs[R]['acceptance'][0].update(requires={'platforms':['win']}),
          lambda rs:rs[R]['acceptance'][0].update(requires={'unknown':True}),
          lambda rs:rs[R]['ratification'].update(unrecognized='x'),
          lambda rs:rs[R]['origin'].update(unrecognized='x'),
          lambda rs:rs[R]['revisions'][0].update(n=True),
          lambda rs:rs[S]['implementation'][0].pop('commit'),
          lambda rs:rs[S]['implementation'][0].pop('path'),
          lambda rs:rs[S]['implementation'][0].update(commit='abc'),
          lambda rs:rs[E]['executor'].update(kind='robot'),
          lambda rs:rs[E]['executor'].update(independence='maybe'),
          lambda rs:rs[E]['source'].update(integrity='TRUST_ME'),
          lambda rs:rs[E]['platform'].update(os='win'),
          lambda rs:rs[E]['observations'][0].update(outcome='green'),
          lambda rs:rs[E]['artifacts'][0].update(sha256='short'),
          lambda rs:rs[E].update(counts={'passed':1.5,'failed':0,'skipped':0,'total':1}),
          lambda rs:rs[E].update(provenance={'assessed':'yes'}),
          lambda rs:rs[R]['applies_to'].update(platforms=[{}]),
        ]
        for i,change in enumerate(cases):
            with self.subTest(case=i):
                rs=complete_records();change(rs);m=self.model(rs)
                self.assertIn('DE-02',self.codes(m));self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED');self.assertFalse(v.gate(m)['passed'])
    def test_catalog_exactly_covers_source_schema_codes_and_extensions(self):
        workspace=Path(os.environ.get('CLX_WORKSPACE_ROOT',r'C:\Users\AnubW\Documents\Projects\CodelaxyWorkspace'))
        path=workspace/'proposals/roadmap-registry/SCHEMA-PROPOSAL.md'
        if not path.exists(): self.skipTest('source proposal is unavailable in this environment')
        text=path.read_text(encoding='utf-8').split('## 8. Kontrolní pravidla')[1].split('## 9.')[0]
        expected=set(re.findall(r'\| `(DE-[0-9]+b?|EM-[0-9]+|AD-[0-9]+)`',text))|{'DE-00','EM-12'}
        self.assertEqual(expected,{r['code'] for r in v.rule_catalog()['rules']})
        self.assertEqual(expected,set(v.RULE_REGISTRY));self.assertTrue(all(callable(f) for f in v.RULE_REGISTRY.values()))

    def test_each_rule_has_a_behavioral_trigger_and_a_nontrigger(self):
        """The table is checked against the catalog; adding a code needs a case.

        Positive=the malformed/missing input emits its named code. Negative=
        a fresh valid fixture does not. Source pinning AD04 is intentionally
        exercised by changing its environmental configuration, not mocking rules.
        """
        def nsobj():
            return {'schema':namespaces.SCHEMA,'namespaces':[{'key':'n','label_pattern':'RT[13]','meaning':'test namespace','authority':REF,'status':'LIVE','maps_to':'REQ','distinct_from':[]}]}
        def alias(): return {'namespace':'n','value':'RT1','status':'ACTIVE','source':copy.deepcopy(REF)}
        def clone_origin(rs):
            x=copy.deepcopy(rs[R]);x['id']='CLX-REQ-0002';rs[x['id']]=x
        def em12(rs): rs[E]['subject']['tree_state']='DIRTY'
        def multplatform(rs): rs[R]['applies_to']['platforms']=['windows','linux'];digest(rs)
        def mutation(rs): rs[S]['method']='mutation';rs[S]['mutant']={'target':'x','description':'disable','baseline_required':True};digest(rs)
        cases={
          'DE-00':lambda rs,kw:rs.clear(),
          'DE-01':lambda rs,kw:None,
          'DE-01b':lambda rs,kw:clone_origin(rs),
          'DE-02':lambda rs,kw:rs[R].update(persistence='TYPO'),
          'DE-03':lambda rs,kw:rs[R].update(depends_on=[{'target':'CLX-REQ-9999'}]),
          'DE-04':lambda rs,kw:rs[R].update(depends_on=[{'target':R}]),
          'DE-05':lambda rs,kw:(rs[R].update(aliases=[alias(),alias()]),kw.update(namespace_catalog=nsobj())),
          'DE-06':lambda rs,kw:(kw.update(base_records=copy.deepcopy(rs)),rs.pop(E)),
          'DE-07':lambda rs,kw:rs[R].update(lifecycle='SUPERSEDED'),
          'DE-08':lambda rs,kw:rs[R].update(revisions=[]),
          'DE-08b':lambda rs,kw:rs[R]['revisions'][0].update(digest='0'*64),
          'DE-09':lambda rs,kw:rs[E].pop('performed_at'),
          'DE-10':lambda rs,kw:rs[E]['evidences'][0].update(requirement_revision=2),
          'DE-11':lambda rs,kw:rs[R].update(verification='VERIFIED'),
          'DE-12':lambda rs,kw:rs[R].update(definition='UNRESOLVED'),
          'DE-13':lambda rs,kw:rs[R]['origin'].update(quote='not in source'),
          'DE-14':lambda rs,kw:rs[S]['verifies'][0].pop('basis'),
          'DE-15':lambda rs,kw:rs[R].update(definition='UNRESOLVED',definition_note='unknown'),
          'DE-16':lambda rs,kw:rs[R].update(asserted_status=[{'status':'DONE'}]),
          'DE-17':lambda rs,kw:rs[R].update(decision='missing'),
          'EM-01':lambda rs,kw:rs[R].update(definition='UNRESOLVED',definition_note='unknown'),
          'EM-02':lambda rs,kw:rs[E].update(result='INCONCLUSIVE'),
          'EM-03':lambda rs,kw:(rs[R].update(persistence='CONTINUOUS'),kw.update(context=self.git_currency(rs,changed=True))),
          'EM-04':lambda rs,kw:rs[E]['source'].update(availability='UNLOCATED'),
          'EM-05':lambda rs,kw:rs[S]['verifies'][0].update(adequacy='ASSERTED'),
          'EM-06':lambda rs,kw:(rs[E].update(result='INCONCLUSIVE'),rs[R].update(asserted_status=[{'status':'DONE','source':REF}])),
          'EM-07':lambda rs,kw:mutation(rs),
          'EM-08':lambda rs,kw:multplatform(rs),
          'EM-09':lambda rs,kw:rs[E].update(observations=[]),
          'EM-10':lambda rs,kw:rs[S].update(verifies=[]),
          'EM-11':lambda rs,kw:(rs[R]['acceptance'].append({'id':'AC-2','text':'Owner accepts','kind':'decision','resolved':True}),digest(rs)),
          'EM-12':lambda rs,kw:em12(rs),
          'AD-01':lambda rs,kw:(rs[R].update(aliases=[alias(),{**alias(),'namespace':'other'}]),kw.update(namespace_catalog={'schema':namespaces.SCHEMA,'namespaces':nsobj()['namespaces']+[{**nsobj()['namespaces'][0],'key':'other'}]})),
          'AD-02':lambda rs,kw:rs[S].update(verifies=[]),
          'AD-03':lambda rs,kw:kw.update(context={'max_scope_commits':1,'scope_commit_ages':{E:2}}),
          'AD-04':lambda rs,kw:None,
          'AD-05':lambda rs,kw:rs[S].update(implementation=[]),
          'AD-06':lambda rs,kw:(rs[R].update(title='RT1'),kw.update(namespace_catalog=nsobj())),
          'AD-07':lambda rs,kw:rs[R].update(persistence='UNSPECIFIED'),
          'AD-08':lambda rs,kw:kw.update(context={'decisions':[{'authority':'owner-message-unrecorded'}]}),
          'AD-09':lambda rs,kw:kw.update(context={'repo':str(self.root/'not-a-repo')}),
        }
        self.assertEqual(set(cases),{r['code'] for r in v.rule_catalog()['rules']})
        for code,change in cases.items():
            with self.subTest(code=code):
                rs=complete_records();kw={};change(rs,kw)
                if code=='DE-01':
                    directory=self.root/'duplicate-store'/'records'/'REQ';directory.mkdir(parents=True)
                    for name in (R,'CLX-REQ-0002'):
                        canon.write_record(directory/(name+'.json'),rs[R])
                    positive=v.check_root(directory.parent.parent,source_catalog=self.cat,source_roots={'ws':str(self.root)})
                else:
                    positive=self.model(rs,**kw)
                self.assertIn(code,self.codes(positive))
                # AD04 is advisory in our legitimate sha256-only fixture; a
                # complete git-pinned version with readable bytes removes it.
                cat=copy.deepcopy(self.cat)
                if code=='AD-04':
                    for src in cat['sources']:
                        for version in src['versions']:
                            version.update(pinning='git-blob',git_blob='a'*40,commit='b'*40)
                good=v.validate(complete_records(),source_catalog=cat,source_roots={'ws':str(self.root)},context={'artifact_root':str(self.root)})
                self.assertNotIn(code,self.codes(good))
    def test_editorial_cannot_recycle_evidence_after_normative_changes(self):
        def deleted(rs): rs[R]['acceptance'].pop()
        def added(rs): rs[R]['acceptance'].append({'id':'AC-3','text':'new obligation','kind':'evidence','resolved':True})
        def renamed(rs): rs[R]['acceptance'][0]['id']='AC-9'
        def platform(rs): rs[R]['applies_to']['platforms']=['linux']
        def requirements(rs): rs[R]['acceptance'][0]['requires']={'independence':'owner'}
        def text(rs): rs[R]['acceptance'][0]['text']='materially different acceptance'
        for change in (deleted,added,renamed,platform,requirements,text):
            base=complete_records();base[R]['acceptance'].append({'id':'AC-2','text':'unproven obligation','kind':'evidence','resolved':True});digest(base)
            self.assertNotEqual(self.model(base)['derived'][R]['verification'],'VERIFIED')
            rs=copy.deepcopy(base);change(rs);rs[R]['revision']=2
            rs[R]['revisions'].append({'n':2,'change_class':'EDITORIAL','digest':canon.normative_digest(rs[R])})
            for base_option in (None,base):
                with self.subTest(change=change.__name__,base=base_option is not None):
                    m=self.model(rs,base_records=base_option)
                    self.assertIn('DE-08',self.codes(m));self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED');self.assertFalse(v.gate(m)['passed'])
    def test_title_note_only_editorial_keeps_identical_digest_evidence(self):
        base=complete_records();rs=copy.deepcopy(base)
        for rid in (R,S):
            rs[rid]['title']+=' clarified';rs[rid]['note']='editorial note only';rs[rid]['revision']=2
            rs[rid]['revisions'].append({'n':2,'change_class':'EDITORIAL','digest':canon.normative_digest(rs[rid])})
        for base_option in (None,base):
            m=self.model(rs,base_records=base_option)
            self.assertTrue(m['valid'],m['findings']);self.assertEqual(m['derived'][R]['verification'],'VERIFIED');self.assertTrue(v.gate(m)['passed'])
    def test_scenario_editorial_with_changed_normative_procedure_cannot_qualify(self):
        base=complete_records();rs=copy.deepcopy(base)
        rs[S]['procedure']='Different procedure';rs[S]['revision']=2
        rs[S]['revisions'].append({'n':2,'change_class':'EDITORIAL','digest':canon.normative_digest(rs[S])})
        m=self.model(rs,base_records=base);self.assertIn('DE-08',self.codes(m));self.assertFalse(v.gate(m)['passed'])
    def test_source_key_and_version_resolve_even_without_quote(self):
        for source,version in (('not-in-catalog','v2'),('doc','v404')):
            rs=complete_records();rs[R]['origin']={'source':source,'version':version,'anchor':'L2'}
            m=self.model(rs);self.assertIn('DE-03',self.codes(m));self.assertFalse(v.gate(m)['passed'])
        rs=complete_records();rs[R]['origin']={'source':'doc','version':'v1','anchor':'L1'}
        (self.root/'v1.md').unlink()
        m=self.model(rs);self.assertIn('AD-04',self.codes(m));self.assertNotIn('DE-03',self.codes(m))
    def test_baseline_observation_conflicts_never_depend_on_order(self):
        for bad in ('FAIL','SKIP','ABSENT','UNVERIFIED','unknown'):
            for order in ((bad,'PASS'),('PASS',bad)):
                with self.subTest(order=order):
                    rs=complete_records()
                    bs=copy.deepcopy(rs[S]);bs['id']='CLX-SCN-0002';bs['verifies'][0]['adequacy']='ASSERTED'
                    b=copy.deepcopy(rs[E]);b.update(id='CLX-EVD-0002',scenario=bs['id'],evidences=[])
                    b['observations']=[{'name':'T.One','outcome':x} for x in order]
                    rs[bs['id']]=bs;rs[b['id']]=b;rs[S].update(method='mutation',mutant={'target':'x','description':'disable','baseline_required':True});rs[E]['baseline']=b['id'];digest(rs)
                    m=self.model(rs);self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED');self.assertFalse(v.gate(m)['passed']);self.assertTrue({'EM-07','EM-09'}<=self.codes(m))
                    self.assertNotEqual(evidence.observation_outcomes(b['observations']).get('T.One'),'PASS')
        rs=complete_records();bs=copy.deepcopy(rs[S]);bs['id']='CLX-SCN-0002';bs['verifies'][0]['adequacy']='ASSERTED'
        b=copy.deepcopy(rs[E]);b.update(id='CLX-EVD-0002',scenario=bs['id'],evidences=[],observations=[{'name':'T.One','outcome':'PASS'}]*2)
        rs[bs['id']]=bs;rs[b['id']]=b;rs[S].update(method='mutation',mutant={'target':'x','description':'disable','baseline_required':True});rs[E]['baseline']=b['id'];digest(rs)
        self.assertEqual(self.model(rs)['derived'][R]['verification'],'VERIFIED')
        self.assertEqual(evidence.observation_outcomes(b['observations']),{'T.One':'PASS'})
        self.assertEqual(evidence.observation_outcomes(None),{})
        for invalid in (None,{},[],17):
            for values in ((invalid,'PASS'),('PASS',invalid)):
                self.assertNotEqual(evidence.observation_outcomes([{'name':'T.One','outcome':x} for x in values]).get('T.One'),'PASS')
    def test_artifact_claims_are_rehashed_and_cannot_escape_the_root(self):
        self.assertEqual(self.model()['derived'][R]['effective_status'],'DONE')
        (self.root/'artifact.txt').write_bytes(b'CHANGED')
        m=self.model();self.assertNotEqual(m['derived'][R]['verification'],'VERIFIED');self.assertIn('EM-04',self.codes(m))
        self.records[E]['artifacts'][0]['locator']='../outside.txt'
        self.assertNotEqual(self.model()['derived'][R]['verification'],'VERIFIED')
        self.records[E]['artifacts'][0]['locator']='https://example.test/not-downloaded'
        self.assertNotEqual(self.model()['derived'][R]['verification'],'VERIFIED')
        (self.root/'artifact.txt').write_bytes(b'PASS\n');(self.root/'artifact-scope').mkdir()
        self.records[E]['artifacts'][0]['locator']='../artifact.txt'
        self.assertNotEqual(self.model(context={'artifact_root':str(self.root/'artifact-scope')})['derived'][R]['verification'],'VERIFIED')
    def test_green_baseline_must_match_subject_and_observe_the_killing_tests(self):
        base_scn=copy.deepcopy(self.records[S]);base_scn['id']='CLX-SCN-0002';base_scn['verifies'][0]['adequacy']='ASSERTED'
        baseline=copy.deepcopy(self.records[E]);baseline.update(id='CLX-EVD-0002',scenario=base_scn['id'],evidences=[])
        self.records[base_scn['id']]=base_scn;self.records[baseline['id']]=baseline
        self.records[S].update(method='mutation',mutant={'target':'x','description':'disable','baseline_required':True})
        self.records[E]['baseline']=baseline['id'];digest(self.records)
        self.assertEqual(self.model()['derived'][R]['verification'],'VERIFIED')
        for change in ('observations','subject','platform','result'):
            original=copy.deepcopy(baseline)
            if change=='observations': baseline[change]=[]
            elif change=='subject': baseline[change]={**baseline[change],'commit':'b'*40}
            elif change=='platform': baseline[change]={'os':'linux'}
            else: baseline[change]='INCONCLUSIVE'
            with self.subTest(change=change): self.assertNotEqual(self.model()['derived'][R]['verification'],'VERIFIED')
            baseline.clear();baseline.update(original)
    def test_git_base_alias_history_uses_actual_repository_objects(self):
        from tests.test_store import git, commit_all, new_root
        root=new_root(self.root/'actual-git');git(root,'init','-q')
        self.records[R]['aliases']=[{'namespace':'n','value':'RT1','status':'ACTIVE','source':REF}]
        for rid,r in self.records.items(): canon.write_record(root/'records'/r['type']/(rid+'.json'),r)
        commit_all(root,'base aliases')
        self.records[R].pop('aliases');canon.write_record(root/'records'/'REQ'/(R+'.json'),self.records[R],overwrite=True)
        m=v.check_root(root,base='HEAD',source_catalog=self.cat,source_roots={'ws':str(self.root)},context={'artifact_root':str(self.root)})
        self.assertIn('DE-06',self.codes(m))
    def test_observed_git_scope_age_excludes_unrelated_changes_and_overrides_claims(self):
        from tests.test_store import git,commit_all
        repo=self.root/'scope-age';repo.mkdir();git(repo,'init','-q')
        (repo/'src').mkdir();(repo/'src/a.cs').write_text('base');(repo/'notes.txt').write_text('base')
        commit_all(repo,'base');base=git(repo,'rev-parse','HEAD').stdout.strip()
        self.records[E]['subject']['commit']=base;self.records[S]['scope_paths']=['src/**/*.cs']
        (repo/'notes.txt').write_text('unrelated');commit_all(repo,'unrelated')
        context={'repo':str(repo),'max_scope_commits':0,'scope_commit_ages':{E:999}}
        self.assertNotIn('AD-03',self.codes(self.model(context=context)))
        (repo/'src/a.cs').write_text('changed');commit_all(repo,'scoped change')
        context['scope_commit_ages'][E]=0
        self.assertIn('AD-03',self.codes(self.model(context=context)))
        context['max_scope_commits']=1
        self.assertNotIn('AD-03',self.codes(self.model(context=context)))
        (repo/'src/a.cs').write_text('changed again');commit_all(repo,'second scoped change')
        self.assertIn('AD-03',self.codes(self.model(context=context)))
    def test_scope_age_git_failure_is_named_without_successful_fallback(self):
        context={'repo':str(self.root/'absent'),'max_scope_commits':0,'scope_commit_ages':{E:999}}
        m=self.model(context=context);self.assertIn('AD-09',self.codes(m));self.assertNotIn('AD-03',self.codes(m))
    def test_clean_tree_legacy_boolean_cannot_contradict_or_replace_tree_state(self):
        self.records[E]['subject']['clean_tree']=False
        self.assertIn('DE-02',self.codes(self.model()));self.assertFalse(v.gate(self.model())['passed'])
        self.records[E]['subject'].pop('tree_state');self.records[E]['subject']['clean_tree']=True
        self.assertNotEqual(self.model()['derived'][R]['verification'],'VERIFIED')

if __name__=='__main__': unittest.main()
