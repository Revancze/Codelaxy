"""S3: read-only composition of registry rules. No decisions are inferred.

validate() returns model/1. Source proofs are re-read; EVD claims are qualified
by the S2 evidence engine. Stored DEC records are deliberately unsupported.
Explicit decision attestations may be supplied in context['decisions']; their
source must itself be hash-verified and RATIFIED/RATIFICATION-RECORD.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from . import aliases, canon, evidence, freshness, namespaces, sources, store
from .findings import Finding, data_error, evidence_missing, advisory

RULES_PATH = Path(__file__).resolve().parent.parent / 'schema' / 'rules.json'
SCHEMA_PATH = RULES_PATH.with_name('registry.schema.json')
DERIVED_FIELDS = {'verification', 'effective_status', 'current_evidence', 'open_conditions', 'evidence_class'}
COMMON = {'schema_version','id','type','title','aliases','note','lifecycle','origin','decision'}
FIELDS = {
 'REQ': COMMON | {'kind','statement','statement_origin','definition','definition_note','open_questions','persistence','ratification','applies_to','acceptance','revision','revisions','finding','assigned_to','ms_ref','depends_on','refines','supersedes','conflicts_with','blocked','asserted_status','inherits_evidence_from'},
 'SCN': COMMON | {'definition','definition_note','method','procedure','procedure_origin','expected','platforms_required','scope_paths','implementation','mutant','independence_required','observation_required','verifies','revision','revisions','depends_on','supersedes'},
 'EVD': COMMON | {'scenario','scenario_revision','evidences','result','performed_at','subject','platform','executor','counts','observations','baseline','artifacts','source','supersedes','provenance','depends_on_revisions'},
 'MIL': COMMON | {'statement','requirements','acceptance','source','ms_ref'},
}
REQUIRED = {
 'REQ': {'kind','statement','statement_origin','lifecycle','definition','persistence','ratification','origin','applies_to','acceptance','revision','revisions'},
 'SCN': {'lifecycle','definition','method','procedure','procedure_origin','expected','platforms_required','verifies','revision','revisions'},
 'EVD': {'lifecycle','scenario','scenario_revision','evidences','result','performed_at','subject','platform','executor','source'},
 'MIL': {'title'},
}
ENUMS = {
 'lifecycle': {'PROPOSED','ACTIVE','SUPERSEDED','WITHDRAWN'},
 'definition': {'DEFINED','UNRESOLVED'}, 'persistence': {'ONCE','CONTINUOUS','UNSPECIFIED'},
 'statement_origin': {'quoted','derived-from-range','authored'}, 'procedure_origin': {'quoted','paraphrase','authored'},
 'kind': {'exit-criterion','gate-condition','finding-closure','test-obligation','process-rule','constraint'},
 'method': {'test','mutation','probe','inspection','review','ci-gate','measurement','change-record'},
 'result': {'PASS','FAIL','INCONCLUSIVE','NOT_RUN'}, 'independence_required': {'none','independent','owner'},
}
PLATFORMS = {'windows','linux','macos','any'}
RELATIONS = ('depends_on','refines','supersedes','inherits_evidence_from')
SOURCE_FIELDS={'source','version','anchor','fragment','quote'}
NESTED={
 'ratification':({'state','source'},{'state'}), 'applies_to':({'platforms','notes'},{'platforms'}),
 'requires':({'platforms','independence','decision_kind','requirements'},set()),
 'acceptance':({'id','text','kind','resolved','requires'},{'id','text','kind','resolved'}),
 'revisions':({'n','digest','change_class'},{'n','digest','change_class'}),
 'verifies':({'requirement','requirement_revision','acceptance','adequacy','basis'},{'requirement','requirement_revision','acceptance','adequacy'}),
 'implementation':({'path','name','test','commit'},{'path','commit'}),
 'evidences':({'requirement','requirement_revision','acceptance'},{'requirement','requirement_revision','acceptance'}),
 'mutant':({'target','description','baseline_required'},{'target','description','baseline_required'}),
 'subject':({'repository','commit','tree','tree_state','clean_tree','fingerprint','branch'},{'repository','commit'}),
 'platform':({'os','os_version','shell','tools','environment','ci'},{'os'}),
 'executor':({'kind','name','session','independence'},{'kind','name','independence'}),
 'source':({'availability','integrity','claimed_by'},{'availability','integrity'}),
 'counts':({'passed','failed','skipped','total'},{'passed','failed','skipped','total'}),
 'observations':({'name','outcome'},{'name','outcome'}), 'artifacts':({'role','locator','sha256'},{'role','locator','sha256'}),
 'depends_on':({'target','source_kind','source'},{'target','source_kind'}),
 'conflicts_with':({'target','status'},{'target','status'}), 'supersedes':({'target','kind'},{'target','kind'}),
 'blocked':({'by','since','note'},{'by','note'}), 'assigned_to':({'milestone','basis','source_kind'},{'milestone','basis'}),
 'finding':({'class','severity','proven'},{'class','proven'}),
 'asserted_status':({'status','as_of','source'},{'status','as_of'}), 'open_questions':({'text','decision'},{'text'}),
 'provenance':({'assessed','proven','unmet','points'},{'assessed'}),
 'points':({'n','name','holds','basis'},{'n','name','holds','basis'}),
 'aliases':({'namespace','value','status','source','range_source','ambiguous_with','note'},{'namespace','value','status','source'}),
}
NESTED_ENUMS={
 ('ratification','state'):{'RATIFIED','PROPOSED','DRAFT','HISTORICAL'},
 ('requires','independence'):{'none','independent','owner'},
 ('acceptance','kind'):{'evidence','decision','requirement'},
 ('revisions','change_class'):{'INITIAL','EDITORIAL','REFINEMENT'},
 ('verifies','adequacy'):{'ASSERTED','ACCEPTED'},
 ('subject','tree_state'):{'CLEAN','DIRTY','UNKNOWN'},
 ('platform','os'):PLATFORMS-{'any'}, ('executor','kind'):{'ci','human','agent'},
 ('executor','independence'):{'author','independent','owner'},
 ('source','availability'):{'AVAILABLE','UNLOCATED','LOST'}, ('source','integrity'):{'HASH_CHECKED','NOT_CHECKED'},
 ('observations','outcome'):{'PASS','FAIL','SKIP','ABSENT','UNVERIFIED'},
 ('depends_on','source_kind'):{'documented','inferred'}, ('conflicts_with','status'):{'OPEN','RESOLVED'},
 ('supersedes','kind'):{'replace','split','merge'}, ('finding','class'):{'DEFECT','GAP','DEBT'},
 ('asserted_status','status'):{'DONE','VERIFIED','PARTIAL','PLANNED','BLOCKED','UNKNOWN','OPEN','UNVERIFIED'},
 ('aliases','status'):{'ACTIVE','HISTORICAL','AMBIGUOUS','REJECTED','IMPLIED_BY_RANGE'},
 ('requires','decision_kind'):{'ratification','acceptance','revision','withdrawal','waiver','disposition','planning','process'},
}
FULL_HASH=re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')
SHA256=re.compile(r'[0-9a-f]{64}')

def _dict(v):
    return v if isinstance(v, dict) else {}

def _list(v):
    return v if isinstance(v, list) else []

def _target(v):
    return v.get('target') if isinstance(v,dict) else v

def _positive(v):
    return type(v) is int and v > 0

def _conditions(r):
    return {a.get('id'):a for a in _list(r.get('acceptance')) if isinstance(a,dict)}

def _revision_numbers(r):
    return {v.get('n') for v in _list(r.get('revisions')) if isinstance(v,dict) and _positive(v.get('n'))}

def _nested(run,rid,field,obj):
    allowed,required=NESTED[field]
    if not isinstance(obj,dict):
        run.add('DE-02',rid,field+' must be an object');return
    if set(obj)-allowed or required-set(obj):
        run.add('DE-02',rid,field+' has unknown or missing fields')
    for key,value in obj.items():
        enum=NESTED_ENUMS.get((field,key))
        if enum is not None and (not isinstance(value,str) or value not in enum):
            run.add('DE-02',rid,field+'.'+key+' unknown enum')
        if key in ('resolved','baseline_required','clean_tree','ci','proven','assessed','holds') and type(value) is not bool:
            run.add('DE-02',rid,field+'.'+key+' must be boolean')
        if key in ('n','requirement_revision') and not _positive(value):
            run.add('DE-02',rid,field+'.'+key+' must be a positive integer')
        if field=='counts' and (type(value) is not int or value<0):
            run.add('DE-02',rid,'counts must be nonnegative integers')
        if key in ('digest','sha256','fingerprint') and (not isinstance(value,str) or not SHA256.fullmatch(value)):
            run.add('DE-02',rid,field+'.'+key+' must be SHA-256')
        if key in ('commit','tree') and (not isinstance(value,str) or not FULL_HASH.fullmatch(value)):
            run.add('DE-02',rid,field+'.'+key+' must be a full Git hash')
        if key in ('platforms',) and (not isinstance(value,list) or not value or any(not isinstance(p,str) or p not in PLATFORMS for p in value)):
            run.add('DE-02',rid,field+'.platforms must be a nonempty platform array')
        if key in ('requirements','unmet','ambiguous_with') and (not isinstance(value,list) or any(not isinstance(x,str) or not x for x in value)):
            run.add('DE-02',rid,field+'.'+key+' must be a string array')
        if key in ('path','name','test','role','locator','repository','target','requirement','acceptance','text','description','note','status','state','kind','method','os','independence','decision_kind','as_of','decided_on','source_kind','availability','integrity','outcome','change_class','adequacy','milestone','since','severity','environment','os_version','shell','session','branch','namespace','value') and (not isinstance(value,str) or not value):
            run.add('DE-02',rid,field+'.'+key+' must be nonempty text')
        if key=='requires': _nested(run,rid,'requires',value)
        if key=='tools' and (not isinstance(value,dict) or any(not isinstance(k,str) or not isinstance(x,str) for k,x in value.items())):
            run.add('DE-02',rid,'platform.tools must map names to versions')
        if key in ('source','claimed_by','range_source') or (key=='basis' and isinstance(value,dict)):
            _source_shape(run,rid,value)
        if key=='basis' and not isinstance(value,(str,dict)):
            run.add('DE-02',rid,field+'.basis must be a source reference or decision id')
        if key=='points':
            if not isinstance(value,list): run.add('DE-02',rid,'provenance.points must be an array')
            else:
                for p in value: _nested(run,rid,'points',p)
        if key=='by':
            if not isinstance(value,list) or not value: run.add('DE-12',rid,'blocked.by must be a nonempty array')
            else:
                for ref in value:
                    if isinstance(ref,dict): _source_shape(run,rid,ref)
                    elif not isinstance(ref,str) or not store.parse_id(ref): run.add('DE-02',rid,'blocked.by has malformed reference')
    if field=='implementation':
        if not (obj.get('name') or obj.get('test')): run.add('DE-02',rid,'implementation requires a test name')
        path=obj.get('path')
        if isinstance(path,str) and (path.startswith('/') or '\\' in path or '..' in path.split('/')):
            run.add('DE-02',rid,'implementation.path must be a repository relative POSIX path')
    if field=='mutant' and obj.get('baseline_required') is not True:
        run.add('DE-12',rid,'mutation baseline_required must be true')
    if field=='subject' and type(obj.get('clean_tree')) is bool and obj.get('tree_state') in ('CLEAN','DIRTY') and obj['clean_tree']!=(obj['tree_state']=='CLEAN'):
        run.add('DE-02',rid,'subject.clean_tree contradicts subject.tree_state')

def _source_shape(run,rid,obj):
    if not isinstance(obj,dict) or not {'source','version'}<=set(obj)<=SOURCE_FIELDS or any(not isinstance(x,str) or not x for x in obj.values()):
        run.add('DE-02',rid,'malformed source reference')

class Run:
    def __init__(self, records, source_catalog, namespace_catalog, source_roots, base_records, context, min_records):
        self.records=records
        self.catalog=source_catalog
        self.namespaces=namespace_catalog
        self.roots=source_roots or {}
        self.base=base_records
        self.context=context or {}
        self.min_records=min_records
        self.findings=[]
        self.derived={}
        self.decisions=_list(self.context.get('decisions'))
        self.base_findings=_list(self.context.get('base_findings'))

    def add(self, code, record, message):
        kind=data_error if code.startswith('DE-') else evidence_missing if code.startswith('EM-') else advisory
        self.findings.append(kind(code,str(record),message))

    def source(self, ref, *, ratified=False):
        if not isinstance(ref,dict) or not self.catalog:
            return False
        try:
            v=sources.find_version(self.catalog,ref.get('source'),ref.get('version'))
            if ratified and v.get('status') not in ('RATIFIED','RATIFICATION-RECORD'):
                return False
            sources.read_verified(self.catalog,self.roots,ref.get('source'),ref.get('version'))
            return not any(f.cls=='DATA_ERROR' for f in sources.check_quote(self.catalog,self.roots,ref))
        except (sources.SourceError,OSError,ValueError):
            return False

    def decision(self, rid, *, effect=None, kind=None, revision=None, key=None):
        for d in self.decisions:
            if not isinstance(d,dict) or d.get('status')!='ACCEPTED' or d.get('authority') not in ('owner-message-recorded','ratified-source'):
                continue
            if not d.get('decided_by') or not d.get('decided_on') or not self.source(d.get('source'),ratified=True):
                continue
            if key is not None and d.get('id')!=key:
                continue
            if kind is not None and d.get('decision_kind')!=kind:
                continue
            if any(isinstance(c,dict) and c.get('record')==rid and (effect is None or c.get('effect')==effect)
                   and (revision is None or c.get('revision')==revision) for c in _list(d.get('concerns'))):
                return True
        return False

def _structure(run):
    origins={}
    for rid,r in run.records.items():
        typ=r.get('type')
        if typ not in FIELDS or r.get('schema_version')!=1 or r.get('id')!=rid or not store.parse_id(rid) or store.parse_id(rid)[0]!=typ:
            run.add('DE-02',rid,'invalid schema/type/identity; DEC is not a stored registry entity')
            continue
        unknown=set(r)-FIELDS[typ]-DERIVED_FIELDS
        if unknown or (REQUIRED[typ] | {'schema_version','id','type','title'})-set(r):
            run.add('DE-02',rid,'unknown or missing fields: '+', '.join(sorted(unknown | ((REQUIRED[typ]|{'schema_version','id','type','title'})-set(r)))))
        if any(k in r for k in DERIVED_FIELDS):
            run.add('DE-11',rid,'derived fields may not be stored')
        for field,values in ENUMS.items():
            if field in r and (not isinstance(r[field],str) or r[field] not in values):
                run.add('DE-02',rid,'unknown enum '+field)
        for field in ('title','statement','procedure','expected'):
            if field in r and (not isinstance(r[field],str) or not r[field].strip()):
                run.add('DE-02',rid,field+' must be nonempty text')
        for field in ('aliases','acceptance','revisions','verifies','implementation','observations','artifacts','evidences','depends_on','refines','supersedes','conflicts_with','inherits_evidence_from','asserted_status','open_questions','scope_paths','platforms_required'):
            if field in r and not isinstance(r[field],list):
                run.add('DE-02',rid,field+' must be an array')
        for field in ('acceptance','revisions','verifies','observations','artifacts','evidences','implementation','aliases','asserted_status'):
            if any(not isinstance(x,dict) for x in _list(r.get(field))):
                run.add('DE-02',rid,field+' items must be objects')
        arrays={'acceptance','revisions','verifies','implementation','evidences','observations','artifacts','depends_on','conflicts_with','asserted_status','open_questions','aliases'}
        for field in set(r)&set(NESTED):
            if field=='source' and typ!='EVD':
                _source_shape(run,rid,r[field]);continue
            if field=='supersedes':
                if not isinstance(r[field],list): run.add('DE-02',rid,'supersedes must be an array')
                else:
                    for item in r[field]:
                        if typ=='EVD':
                            if not isinstance(item,str) or not store.parse_id(item): run.add('DE-02',rid,'evidence supersedes needs record ids')
                        else: _nested(run,rid,field,item)
            elif field in arrays:
                for item in _list(r[field]): _nested(run,rid,field,item)
            else: _nested(run,rid,field,r[field])
        if 'origin' in r: _source_shape(run,rid,r['origin'])
        for field in ('scope_paths','platforms_required','refines','inherits_evidence_from','requirements'):
            if field in r and (not isinstance(r[field],list) or any(not isinstance(x,str) or not x for x in r[field])):
                run.add('DE-02',rid,field+' must be a string array')
        if 'depends_on_revisions' in r and (not isinstance(r['depends_on_revisions'],dict) or any(not isinstance(k,str) or not _positive(x) for k,x in r['depends_on_revisions'].items())):
            run.add('DE-02',rid,'depends_on_revisions must map ids to positive revisions')
        if 'observation_required' in r and type(r['observation_required']) is not bool:
            run.add('DE-02',rid,'observation_required must be boolean')
        if typ=='EVD' and not _positive(r.get('scenario_revision')):
            run.add('DE-02',rid,'scenario_revision must be positive')
        if typ=='EVD' and 'performed_at' in r:
            try:
                value=r['performed_at']
                if not isinstance(value,str) or not re.match(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T|$)',value): raise ValueError('not ISO date/time')
                datetime.fromisoformat(value)
            except (ValueError,TypeError): run.add('DE-02',rid,'performed_at must be an ISO date/time')
        if typ in ('REQ','SCN') and not _positive(r.get('revision')):
            run.add('DE-02',rid,'revision must be positive')
        if r.get('definition')=='UNRESOLVED' and not r.get('definition_note'):
            run.add('DE-12',rid,'UNRESOLVED requires definition_note')
        if 'blocked' in r and (not isinstance(r['blocked'],dict) or not _list(r['blocked'].get('by'))):
            run.add('DE-12',rid,'blocked requires nonempty by')
        if typ=='REQ':
            platforms=_dict(r.get('applies_to')).get('platforms')
            if not isinstance(platforms,list) or not platforms or any(p not in PLATFORMS for p in platforms):
                run.add('DE-02',rid,'applies_to.platforms must be a nonempty platform array')
            seen=set()
            for ac in _list(r.get('acceptance')):
                if not isinstance(ac,dict): continue
                a=ac.get('id')
                if not isinstance(a,str) or not re.fullmatch(r'AC-[1-9][0-9]*',a) or a in seen or type(ac.get('resolved')) is not bool or ac.get('kind') not in ('evidence','decision','requirement') or not ac.get('text'):
                    run.add('DE-02',rid,'malformed or duplicate acceptance condition')
                seen.add(str(a))
                if set(ac)-{'id','text','kind','resolved','requires'}:
                    run.add('DE-02',rid,'unknown acceptance field')
                requires=_dict(ac.get('requires'))
                if 'independence' in requires and requires['independence'] not in ('none','independent','owner'):
                    run.add('DE-02',rid,'unknown independence')
                if 'platforms' in requires and (not isinstance(requires['platforms'],list) or not requires['platforms'] or any(p not in PLATFORMS for p in requires['platforms'])):
                    run.add('DE-02',rid,'invalid condition platforms')
            if not _list(r.get('acceptance')):
                run.add('DE-12',rid,'requirement has no acceptance condition')
            rat=_dict(r.get('ratification'))
            if rat.get('state') not in ('RATIFIED','PROPOSED','DRAFT','HISTORICAL'):
                run.add('DE-02',rid,'unknown ratification state')
            if r.get('lifecycle')=='ACTIVE':
                o=_dict(r.get('origin'))
                key=tuple(str(o.get(k,'')) for k in ('source','version','anchor','fragment'))
                if any(key): origins.setdefault(key,[]).append(rid)
            for status in _list(r.get('asserted_status')):
                if isinstance(status,dict) and status.get('status') in ('DONE','VERIFIED') and not status.get('source'):
                    run.add('DE-16',rid,'asserted completion needs a source')
        if typ=='SCN':
            p=r.get('platforms_required')
            if not isinstance(p,list) or not p or any(v not in PLATFORMS for v in p):
                run.add('DE-02',rid,'invalid platforms_required')
            if r.get('method')=='mutation' and not _dict(r.get('mutant')).get('baseline_required'):
                run.add('DE-12',rid,'mutation requires mutant.baseline_required')
            if not _list(r.get('verifies')):
                run.add('DE-12',rid,'scenario selects no requirement')
            for impl in _list(r.get('implementation')):
                if isinstance(impl,dict) and not (impl.get('name') or impl.get('test')):
                    run.add('DE-02',rid,'implementation needs a test name')
        if typ=='EVD':
            if r.get('lifecycle') not in ('ACTIVE','SUPERSEDED'):
                run.add('DE-02',rid,'invalid evidence lifecycle')
            if _dict(r.get('platform')).get('os') not in PLATFORMS-{'any'}:
                run.add('DE-02',rid,'invalid evidence platform')
            run.findings.extend(evidence.validate_evd(r,rid))
    for ids in origins.values():
        if len(ids)>1:
            for rid in ids: run.add('DE-01b',rid,'duplicate ACTIVE origin: '+', '.join(sorted(ids)))

def _references(run):
    ids=set(run.records)
    for rid,r in run.records.items():
        refs=[]
        for field in RELATIONS+('conflicts_with',):
            refs += [_target(v) for v in _list(r.get(field))]
        refs += [_dict(r.get('assigned_to')).get('milestone')]
        if r.get('type')=='EVD': refs += [r.get('scenario'),r.get('baseline')]
        for field in ('verifies','evidences'):
            refs += [v.get('requirement') for v in _list(r.get(field)) if isinstance(v,dict)]
        for ac in _conditions(r).values():
            refs += _list(_dict(ac.get('requires')).get('requirements'))
        for ref in refs:
            if ref is not None and (not isinstance(ref,str) or ref not in ids):
                run.add('DE-03',rid,'unknown record reference '+repr(ref))
        for field in RELATIONS:
            stack=[(rid,())]
            while stack:
                node,path=stack.pop()
                if node in path:
                    run.add('DE-04',rid,'cycle in '+field+': '+' -> '.join(path+(node,)))
                    break
                for v in _list(run.records.get(node,{}).get(field)):
                    ref=_target(v)
                    if isinstance(ref,str) and ref in ids: stack.append((ref,path+(node,)))

def _sources(run):
    if run.catalog is not None:
        cat_findings=sources.validate_catalog(run.catalog)
        run.findings.extend(cat_findings)
        if not any(f.cls=='DATA_ERROR' for f in cat_findings): run.findings.extend(sources.verify_files(run.catalog,run.roots))
    if run.namespaces is not None:
        ns_findings=namespaces.validate_namespaces(run.namespaces,run.catalog)
        run.findings.extend(ns_findings)
        if run.catalog and not any(f.cls=='DATA_ERROR' for f in ns_findings):
            run.findings.extend(namespaces.check_authorities(run.namespaces,run.catalog,run.roots))
            run.findings.extend(aliases.check_aliases(run.records,run.namespaces,run.catalog,run.roots))
    elif any(_list(r.get('aliases')) for r in run.records.values()):
        run.add('DE-03','namespaces','aliases require a namespace catalog')
    def walk(v):
        if isinstance(v,dict):
            if 'source' in v and 'version' in v and isinstance(v['source'],str):
                yield v
            for x in v.values(): yield from walk(x)
        elif isinstance(v,list):
            for x in v: yield from walk(x)
    for rid,r in run.records.items():
        for ref in walk(r):
            if not run.catalog:
                run.add('AD-04',rid,'source cannot be checked without source catalog')
            else:
                try:
                    sources.find_version(run.catalog,ref.get('source'),ref.get('version'))
                except sources.SourceLookupError:
                    run.add('DE-03',rid,'unknown source/version: '+str(ref.get('source'))+'/'+str(ref.get('version')))
                    continue
                if 'quote' in ref:
                    run.findings.extend(sources.check_quote(run.catalog,run.roots,ref))
        rat=_dict(r.get('ratification'))
        if rat.get('state')=='RATIFIED':
            if r.get('statement_origin')=='authored' or not rat.get('source'):
                run.add('DE-13',rid,'authored or unreferenced content cannot claim ratification')
            elif not run.source(rat['source'],ratified=True):
                run.add('DE-13',rid,'ratification source is not proven as ratified pinned bytes')
        for link in _list(r.get('depends_on')):
            if isinstance(link,dict) and link.get('source_kind')=='documented' and not run.source(link.get('source')):
                run.add('DE-13',rid,'documented dependency needs a verified source')
        if isinstance(r.get('assigned_to'),dict) and not run.source(r['assigned_to'].get('basis')):
            run.add('DE-13',rid,'milestone assignment needs a verified source basis')
        if r.get('type')=='SCN':
            for v in _list(r.get('verifies')):
                if isinstance(v,dict) and v.get('adequacy')=='ACCEPTED':
                    basis=v.get('basis')
                    if not ((isinstance(basis,dict) and run.source(basis,ratified=True)) or (isinstance(basis,str) and run.decision(v.get('requirement'),key=basis))):
                        run.add('DE-14',rid,'ACCEPTED adequacy needs a proven ratified source or accepted decision')
        if r.get('decision') and not run.decision(rid,key=r['decision']):
            run.add('DE-17',rid,'decision is missing, unaccepted, unproven or does not concern this record')
    if run.base is not None:
        old_aliases=aliases.alias_map(run.base)
        new_aliases=aliases.alias_map(run.records)
        run.findings.extend(aliases.check_moves(old_aliases,new_aliases))
        for key,owners in old_aliases.items():
            if not new_aliases.get(key):
                run.add('DE-06',key[0]+':'+key[1],'alias from base was removed; withdrawal does not erase historical identity')
        if run.context.get('base_source_catalog') is not None and run.catalog is not None:
            run.findings.extend(sources.check_transition(run.context['base_source_catalog'],run.catalog))

def _history(run):
    successors={}
    for rid,r in run.records.items():
        for old in _list(r.get('supersedes')):
            target=_target(old)
            if isinstance(target,str):
                successors.setdefault(target,[]).append(rid)
                if target in run.records and run.records[target].get('lifecycle') not in ('SUPERSEDED','WITHDRAWN'):
                    run.add('DE-07',rid,'superseded target is not retired')
    for rid,r in run.records.items():
        if r.get('lifecycle')=='SUPERSEDED' and rid not in successors:
            run.add('DE-07',rid,'SUPERSEDED has no successor')
        if r.get('lifecycle')=='WITHDRAWN' and not run.decision(rid,effect='withdrawn'):
            run.add('DE-07',rid,'withdrawal needs accepted documented decision')
        if r.get('type') not in ('REQ','SCN'): continue
        history=_list(r.get('revisions'))
        nums=[v.get('n') for v in history if isinstance(v,dict)]
        rev=r.get('revision')
        if not _positive(rev) or nums!=list(range(1,rev+1)):
            run.add('DE-08',rid,'revisions must be contiguous 1..revision')
        try: digest=canon.normative_digest(r)
        except (ValueError,TypeError,KeyError):
            run.add('DE-08b',rid,'cannot digest normative content')
            digest=None
        if not history or not isinstance(history[-1],dict) or history[-1].get('digest')!=digest:
            run.add('DE-08b',rid,'latest normative digest differs')
        for index,v in enumerate(history):
            if not isinstance(v,dict): continue
            if v.get('change_class') not in ('INITIAL','EDITORIAL','REFINEMENT'):
                run.add('DE-02',rid,'unknown revision change class')
            if v.get('change_class')=='REFINEMENT' and not run.decision(rid,effect='revised',revision=v.get('n')):
                run.add('DE-08',rid,'REFINEMENT requires accepted revision decision')
            if v.get('change_class')=='EDITORIAL' and (index==0 or not isinstance(history[index-1],dict) or v.get('digest')!=history[index-1].get('digest')):
                run.add('DE-08',rid,'EDITORIAL cannot change normative content; identical adjacent digests are required')
        if run.base is not None and rid in run.base:
            old=run.base[rid]
            oldhistory={v.get('n'):v.get('digest') for v in _list(old.get('revisions')) if isinstance(v,dict)}
            if any(v.get('n') in oldhistory and v.get('digest')!=oldhistory[v['n']] for v in history if isinstance(v,dict)):
                run.add('DE-08b',rid,'an existing revision digest was changed')
            try: changed=canon.normative_digest(old)!=digest
            except (ValueError,TypeError,KeyError): changed=True
            if changed and (not _positive(rev) or rev<=old.get('revision',0)):
                run.add('DE-08',rid,'normative content changed without revision increase')
            if changed and history and isinstance(history[-1],dict) and history[-1].get('change_class')=='EDITORIAL':
                run.add('DE-08',rid,'normative content differs from actual base despite EDITORIAL declaration')
    if run.base is not None:
        for rid in sorted(set(run.base)-set(run.records)):
            run.add('DE-06',rid,'record from base was removed')
        for rid in sorted(set(run.base)&set(run.records)):
            if run.base[rid].get('type')=='EVD' and run.base[rid]!=run.records[rid]:
                # Lifecycle retirement is the sole allowed update. Observations
                # are append-only; corrections need a new superseding evidence.
                old={k:x for k,x in run.base[rid].items() if k!='lifecycle'}
                new={k:x for k,x in run.records[rid].items() if k!='lifecycle'}
                if old!=new: run.add('DE-06',rid,'evidence observation was modified instead of superseded')

def _bindings(run):
    scenarios={rid:r for rid,r in run.records.items() if r.get('type')=='SCN'}
    for rid,r in run.records.items():
        field='verifies' if r.get('type')=='SCN' else 'evidences' if r.get('type')=='EVD' else None
        for binding in _list(r.get(field)) if field else []:
            if not isinstance(binding,dict): continue
            req=run.records.get(binding.get('requirement'),{})
            ac=_conditions(req).get(binding.get('acceptance'))
            if req.get('type')!='REQ' or ac is None or binding.get('requirement_revision') not in _revision_numbers(req):
                run.add('DE-10',rid,'binding selects nonexistent requirement revision or condition')
            if req.get('definition')=='UNRESOLVED' or (ac and ac.get('resolved') is False):
                run.add('DE-15',rid,'binding to an unresolved requirement or condition is forbidden')
            if r.get('type')=='EVD':
                scn=scenarios.get(r.get('scenario'),{})
                if r.get('scenario_revision') not in _revision_numbers(scn) or not any(isinstance(v,dict) and all(v.get(k)==binding.get(k) for k in ('requirement','acceptance','requirement_revision')) for v in _list(scn.get('verifies'))):
                    run.add('DE-10',rid,'evidence binding does not match VERIFIES/scenario revision')

def _normal_scenarios(records):
    # SCHEMA uses implementation.name; S2 engine uses implementation.test.
    result=copy.deepcopy(records)
    for r in result.values():
        if r.get('lifecycle')!='ACTIVE' or r.get('definition')!='DEFINED':
            r['verifies']=[]
        for impl in _list(r.get('implementation')):
            if isinstance(impl,dict) and 'test' not in impl and 'name' in impl: impl['test']=impl['name']
    return result

def _baseline_ok(e, evidences, scenarios):
    baseline=evidences.get(e.get('baseline'),{})
    scenario=scenarios.get(e.get('scenario'),{})
    base_scenario=scenarios.get(baseline.get('scenario'),{})
    names=[i.get('test',i.get('name')) for i in _list(scenario.get('implementation')) if isinstance(i,dict)]
    observations=evidence.observation_outcomes(baseline.get('observations'))
    return bool(names) and all(observations.get(n)=='PASS' for n in names) and baseline.get('result')=='PASS' and baseline.get('lifecycle')=='ACTIVE' and evidence.classify(baseline).cls=='COMMIT_BOUND' and base_scenario.get('method')=='test' and base_scenario.get('lifecycle')=='ACTIVE' and base_scenario.get('definition')=='DEFINED' and _dict(baseline.get('subject')).get('repository')==_dict(e.get('subject')).get('repository') and _dict(baseline.get('subject')).get('commit')==_dict(e.get('subject')).get('commit') and _dict(baseline.get('platform')).get('os')==_dict(e.get('platform')).get('os')

def _scope_commit_age(repo, evidence_commit, ref, masks):
    """Observed count of commits after the evidence touching its scope.

    Every introduced commit is counted once, including merge commits, whose
    changed paths are the union of diffs against their parents. Empty scope is
    conservative and counts all introduced commits. No caller-provided age can
    replace this observation when a repository was configured.
    """
    start=freshness._resolve(repo,evidence_commit)
    head=freshness._resolve(repo,ref)
    relation=freshness._git(repo,'merge-base','--is-ancestor',start,head)
    if relation.returncode!=0:
        raise freshness.FreshnessError('scope age unavailable: evidence is not an ancestor or Git failed')
    listing=freshness._git(repo,'rev-list',start+'..'+head)
    if listing.returncode!=0:
        raise freshness.FreshnessError('Git could not enumerate scope commit age')
    commits=listing.stdout.decode('ascii').splitlines()
    if not masks: return len(commits)
    for mask in masks: freshness.matches('',mask)  # validates the same POSIX masks as Q8
    count=0
    for commit in commits:
        delta=freshness._git(repo,'diff-tree','-m','--root','--no-commit-id','--name-only','-r','--no-renames','-z',commit)
        if delta.returncode!=0:
            raise freshness.FreshnessError('Git could not read scoped changes of '+commit)
        paths=[p.decode('utf-8','surrogateescape') for p in delta.stdout.split(b'\0') if p]
        if any(freshness.matches(path,mask) for path in paths for mask in masks): count+=1
    return count

def _derive(run):
    reqs={rid:r for rid,r in run.records.items() if r.get('type')=='REQ'}
    scns=_normal_scenarios({rid:r for rid,r in run.records.items() if r.get('type')=='SCN'})
    evds={rid:r for rid,r in run.records.items() if r.get('type')=='EVD'}
    evds=copy.deepcopy(evds)
    artifact_root=run.context.get('artifact_root')
    for eid,e in evds.items():
        if _dict(e.get('source')).get('availability')!='AVAILABLE': continue
        for artifact in _list(e.get('artifacts')):
            locator=_dict(artifact).get('locator')
            try:
                if not artifact_root or not isinstance(locator,str) or '://' in locator:
                    raise OSError('artifact locator has no configured local proof root')
                root=Path(artifact_root).resolve()
                path=(root/locator).resolve()
                path.relative_to(root)
                if path.is_symlink() or not path.is_file(): raise OSError('artifact missing or unsafe')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=artifact.get('sha256'):
                    raise OSError('artifact SHA-256 differs')
            except (OSError,ValueError):
                e['source']={**_dict(e.get('source')),'integrity':'NOT_CHECKED'}
                run.add('EM-04',eid,'artifact could not be located and hash-verified: '+str(locator))
    for e in evds.values():
        scenario=scns.get(e.get('scenario'),{})
        if scenario.get('method')=='mutation':
            if not _baseline_ok(e,evds,scns):
                e.pop('baseline',None)
    env=copy.deepcopy(run.context)
    # Serialized/caller-supplied verdicts are claims, never observations. Q8
    # starts unproven for every evidence and only actual Git assessment below
    # may replace it. ONCE does not depend on Q8, per the schema.
    env['freshness']={eid:'UNDETERMINED' for eid in evds}
    def equivalent(r):
        history=_list(r.get('revisions'))
        if not history or not isinstance(history[-1],dict): return ()
        values=[history[-1].get('n')]
        for index in range(len(history)-1,0,-1):
            item,previous=history[index],history[index-1]
            if not isinstance(item,dict) or not isinstance(previous,dict) or item.get('change_class')!='EDITORIAL' or item.get('digest')!=previous.get('digest'): break
            values.append(previous.get('n'))
        return tuple(values)
    env['equivalent_revisions']={rid:equivalent(r) for rid,r in reqs.items()}
    env['equivalent_scenario_revisions']={rid:equivalent(r) for rid,r in scns.items()}
    for eid,e in evds.items():
        scenario=scns.get(e.get('scenario'),{})
        if run.context.get('repo'):
            try:
                f=freshness.assess(run.context['repo'],_dict(e.get('subject')).get('commit'),run.context.get('ref','HEAD'),scenario.get('scope_paths'))
                dependencies=freshness.check_dependencies(e.get('depends_on_revisions'),{rid:r.get('revision') for rid,r in reqs.items()})
                f=freshness.combine(f,dependencies)
                env['freshness'][eid]=f.state
                run.findings.extend(f.findings)
            except freshness.FreshnessError as ex:
                env['freshness'][eid]='UNDETERMINED'
                run.add('AD-09',eid,str(ex))
        # Scope age is advisory only. In a live repository it is measured from
        # Git, never replaced by an arbitrary caller-provided smaller number.
        threshold=run.context.get('max_scope_commits')
        if type(threshold) is int and threshold>=0:
            try:
                if run.context.get('repo'):
                    age=_scope_commit_age(run.context['repo'],_dict(e.get('subject')).get('commit'),run.context.get('ref','HEAD'),scenario.get('scope_paths'))
                else:
                    age=_dict(run.context.get('scope_commit_ages')).get(eid)
                if type(age) is int and age>=0 and age>threshold:
                    run.add('AD-03',eid,f'evidence age is {age} scope-touching commits; configured maximum {threshold}')
            except freshness.FreshnessError as ex:
                env['freshness'][eid]='UNDETERMINED'
                run.add('AD-09',eid,str(ex))
    pending=set(reqs)
    for _ in range(len(reqs)+1):
        progressed=False
        for rid in sorted(pending):
            r=reqs[rid]
            dependencies=[x for a in _conditions(r).values() if a.get('kind')=='requirement' for x in _list(_dict(a.get('requires')).get('requirements'))]
            if any(x in pending and x!=rid for x in dependencies): continue
            try: d=evidence.derive(r,scns,evds,env)
            except (TypeError,ValueError,KeyError,AttributeError):
                run.add('DE-02',rid,'malformed data cannot be derived')
                run.derived[rid]={'verification':'UNKNOWN','effective_status':'UNKNOWN','conditions':{},'provisional':[]}
                pending.remove(rid); progressed=True; continue
            conditions=dict(d.conditions)
            for acid,ac in _conditions(r).items():
                if ac.get('kind')=='decision':
                    conditions[acid]='SATISFIED' if ac.get('resolved') is True and run.decision(rid,kind=_dict(ac.get('requires')).get('decision_kind')) else 'OPEN'
                if ac.get('kind')=='requirement':
                    refs=_list(_dict(ac.get('requires')).get('requirements'))
                    vals=[run.derived.get(x,{}).get('effective_status','UNKNOWN') for x in refs]
                    conditions[acid]='UNDETERMINED' if ac.get('resolved') is not True or not refs or 'UNKNOWN' in vals else 'SATISFIED' if all(x=='DONE' for x in vals) else 'OPEN'
            checked=[conditions.get(aid,'OPEN') for aid,a in _conditions(r).items() if a.get('kind')!='decision']
            if r.get('definition')=='UNRESOLVED': verification='UNKNOWN'
            elif 'FAILED' in checked: verification='FAILED'
            elif 'UNDETERMINED' in checked: verification='UNKNOWN'
            elif checked and all(x=='SATISFIED' for x in checked): verification='VERIFIED'
            elif checked and all(x in ('SATISFIED','STALE') for x in checked) and 'STALE' in checked: verification='STALE'
            elif any(x in ('SATISFIED','PARTIAL') for x in checked): verification='PARTIALLY_VERIFIED'
            else: verification='UNVERIFIED'
            if r.get('lifecycle') in ('SUPERSEDED','WITHDRAWN'): effective='retired'
            elif verification in ('UNKNOWN','STALE'): effective='UNKNOWN'
            elif r.get('blocked'): effective='BLOCKED'
            elif r.get('lifecycle')=='ACTIVE' and verification=='VERIFIED' and all(conditions.get(aid)=='SATISFIED' for aid,a in _conditions(r).items() if a.get('kind')=='decision'): effective='DONE'
            elif r.get('kind')=='finding-closure' and _dict(r.get('finding')).get('proven'): effective='OPEN'
            elif verification in ('VERIFIED','PARTIALLY_VERIFIED'): effective='PARTIAL'
            else: effective='UNVERIFIED'
            run.derived[rid]={'verification':verification,'effective_status':effective,'conditions':conditions,'provisional':[[*x[:-1],list(x[-1])] for x in d.provisional]}
            run.findings.extend(d.findings)
            pending.remove(rid); progressed=True
        if not progressed: break
    for rid in pending:
        run.derived[rid]={'verification':'UNKNOWN','effective_status':'UNKNOWN','conditions':{},'provisional':[]}
        run.add('DE-04',rid,'cyclic acceptance requirement dependency')
def _diagnostics(run):
    scns={rid:r for rid,r in run.records.items() if r.get('type')=='SCN'}
    evds={rid:r for rid,r in run.records.items() if r.get('type')=='EVD'}
    for rid,r in run.records.items():
        if r.get('type')=='REQ':
            related=[s for s in scns.values() if any(isinstance(v,dict) and v.get('requirement')==rid for v in _list(s.get('verifies')))]
            if r.get('lifecycle')=='ACTIVE' and r.get('definition')=='UNRESOLVED': run.add('EM-01',rid,'UNRESOLVED definition')
            if not related: run.add('AD-02',rid,'requirement has no scenario')
            if r.get('persistence')=='UNSPECIFIED': run.add('AD-07',rid,'UNSPECIFIED is treated as CONTINUOUS')
            d=run.derived.get(rid,{})
            for acid,ac in _conditions(r).items():
                state=d.get('conditions',{}).get(acid,'UNDETERMINED')
                if state!='SATISFIED': run.add('EM-02',rid+'/'+str(acid),'condition '+state)
                if state=='STALE': run.add('EM-03',rid,'only stale evidence for '+str(acid))
                if ac.get('kind')=='decision' and state!='SATISFIED': run.add('EM-11',rid,'no proven accepted owner decision for '+str(acid))
                links=[v for s in related for v in _list(s.get('verifies')) if isinstance(v,dict) and v.get('requirement')==rid and v.get('acceptance')==acid]
                if ac.get('kind')=='evidence' and not any(v.get('adequacy')=='ACCEPTED' for v in links): run.add('EM-10',rid,'no ACCEPTED scenario for '+str(acid))
                if links and all(v.get('adequacy')=='ASSERTED' for v in links): run.add('EM-05',rid,'all scenario links merely ASSERTED')
                wanted=_dict(ac.get('requires')).get('platforms') or _dict(r.get('applies_to')).get('platforms') or []
                if ac.get('kind')=='evidence' and state!='SATISFIED' and len(wanted)>1: run.add('EM-08',rid,'not every required platform has qualifying evidence')
            if any(isinstance(s,dict) and ((s.get('status')=='DONE' and d.get('effective_status')!='DONE') or (s.get('status')=='VERIFIED' and d.get('verification')!='VERIFIED')) for s in _list(r.get('asserted_status'))):
                run.add('EM-06',rid,'asserted completion exceeds derived state')
        if r.get('type')=='SCN' and not _list(r.get('implementation')): run.add('AD-05',rid,'manual scenario has no implementation')
        if r.get('type')=='EVD':
            scn=scns.get(r.get('scenario'),{})
            if evidence.classify(r).cls in ('UNLOCATED','UNVERIFIED_RESULT'): run.add('EM-04',rid,'evidence source/result not verified')
            ranks={'none':0,'author':0,'independent':1,'owner':2}
            if ranks.get(_dict(r.get('executor')).get('independence'),-1)<ranks.get(scn.get('independence_required','none'),0):
                run.add('EM-04',rid,'evidence executor is not independent enough')
            if scn.get('method')=='mutation':
                if not _baseline_ok(r,evds,scns):
                    run.add('EM-07',rid,'mutation lacks qualifying green baseline or killing tests')
            if scn.get('method') in ('test','mutation') or scn.get('observation_required'):
                names=[i.get('test',i.get('name')) for i in _list(scn.get('implementation')) if isinstance(i,dict)]
                obs=evidence.observation_outcomes(r.get('observations'))
                if not names or any(obs.get(n)!='PASS' for n in names): run.add('EM-09',rid,'no PASS observation for every implementing test')
        for d in run.decisions:
            if isinstance(d,dict) and d.get('authority')=='owner-message-unrecorded': run.add('AD-08',d.get('id','decision'),'owner message has no recorded source')
    # Heuristic labels are diagnostics, never alias creation.
    if isinstance(run.namespaces,dict):
        index=aliases.build_index(run.records)
        for rid,r in run.records.items():
            text=' '.join(str(r.get(k,'')) for k in ('title','statement','procedure','expected'))
            for ns in _list(run.namespaces.get('namespaces')):
                if not isinstance(ns,dict): continue
                try:
                    pat=re.compile(ns.get('label_pattern','(?!)'))
                    for token in re.findall(r'[A-Za-z][A-Za-z0-9_.-]*',text):
                        if pat.fullmatch(token) and (ns.get('key'),token) not in index: run.add('AD-06',rid,'unmapped label '+str(ns.get('key'))+':'+token)
                except (re.error,TypeError): pass

CHECKS=(_structure,_references,_sources,_history,_bindings,_derive,_diagnostics)

def rule_catalog():
    return json.loads(RULES_PATH.read_text(encoding='utf-8'))

def _registered_rule(code):
    """Output adapter for one catalog code over the shared inspection pass.

    Rule functions share source/graph/digest work; they do not each re-read all
    sources. Removing a registration removes its findings and is caught by the
    per-code behavioral coverage table.
    """
    def inspect(run):
        return [f for f in run.findings if f.code==code]
    inspect.__name__=code.replace('-','_')
    return inspect

RULE_REGISTRY={row['code']:_registered_rule(row['code']) for row in rule_catalog()['rules']}

def validate(records, *, source_catalog=None, namespace_catalog=None, source_roots=None, base_records=None, context=None, min_records=1):
    """Pure model assembly except reading pinned sources and optional Git currency.

    context: repo/ref, decisions, base_findings,
    base_source_catalog, max_scope_commits/scope_commit_ages. external_findings
    and supplied freshness/equivalent-revision maps are deliberately ignored for
    authority over verdicts. Only live Git observations establish Q8 CURRENT.
    """
    if not isinstance(records,dict):
        raise ValueError('records must be id -> object mapping; use store.load for duplicate-safe disk input')
    if type(min_records) is not int or min_records<1: raise ValueError('min_records must be >= 1')
    safe={k:v for k,v in records.items() if isinstance(k,str) and isinstance(v,dict)}
    run=Run(safe,source_catalog,namespace_catalog,source_roots,base_records,context,min_records)
    if len(safe)!=len(records): run.add('DE-02','registry','malformed record mapping')
    if len(safe)<min_records: run.add('DE-00','registry',f'examined {len(safe)} records; expected at least {min_records}')
    run.findings.extend(f for f in run.base_findings if isinstance(f,Finding))
    for check in CHECKS:
        try: check(run)
        except (TypeError,ValueError,KeyError,AttributeError,RecursionError) as ex:
            run.add('DE-02','registry',check.__name__+' cannot inspect malformed data: '+str(ex))
    # Preserve only stable, unique findings. Rule catalog is executable inventory:
    # unknown emitted codes fail closed instead of disappearing from reports.
    catalog=rule_catalog()
    codes={r['code'] for r in catalog['rules']}
    unknown={f.code for f in run.findings}-codes
    if unknown: run.add('DE-02','rules','uncatalogued rule output '+','.join(sorted(unknown)))
    findings=sorted({(f.cls,f.code,f.record,f.message) for code in sorted(RULE_REGISTRY) for f in RULE_REGISTRY[code](run)})
    if any(f[0]=='DATA_ERROR' for f in findings):
        for d in run.derived.values():
            if d['verification']=='VERIFIED': d['verification']='UNKNOWN'
            if d['effective_status']=='DONE': d['effective_status']='UNKNOWN'
    return {'schema':'model/1','records':[copy.deepcopy(safe[k]) for k in sorted(safe)],'derived':dict(sorted(run.derived.items())),
            'findings':[{'class':c,'code':code,'record':rid,'message':msg} for c,code,rid,msg in findings],
            'examined':len(safe),'rule_counts':{code:sum(f[1]==code for f in findings) for code in sorted(codes)},
            'valid':not any(f[0]=='DATA_ERROR' for f in findings)}

def check_root(root, *, base=None, **kwargs):
    st=store.load(root)
    context=dict(kwargs.pop('context',{}) or {})
    context.setdefault('artifact_root',str(root))
    context['base_findings']=list(st.findings)
    base_records=None
    if base is not None:
        context['base_findings']+=store.check_against_base(root,base)
        base_records=store.base_objects(root,base)
    return validate({r.id:r.obj for r in st.records.values()},base_records=base_records,context=context,**kwargs)

def gate(model, target=None):
    records={r['id']:r for r in model.get('records',[]) if isinstance(r,dict) and 'id' in r}
    if target is None: selected=sorted(model.get('derived',{}))
    elif target not in records: return {'passed':False,'failing':[{'requirement':target,'verification':'UNKNOWN','reason':'unknown target'}],'provisional':[]}
    elif records[target].get('type')=='MIL':
        selected=sorted(rid for rid,r in records.items() if _dict(r.get('assigned_to')).get('milestone')==target)
        selected=sorted(set(selected)|set(_list(records[target].get('requirements'))))
    else: selected=[target] if records[target].get('type')=='REQ' else []
    failing=[{'requirement':rid,'verification':model.get('derived',{}).get(rid,{}).get('verification','UNKNOWN')} for rid in selected if model.get('derived',{}).get(rid,{}).get('effective_status')!='DONE']
    blockers=[f for f in model.get('findings',[]) if f.get('class')=='DATA_ERROR' or f.get('code')=='EM-06']
    provisional=[{'requirement':rid,'evidence':p} for rid in selected for p in model.get('derived',{}).get(rid,{}).get('provisional',[])]
    return {'passed':bool(selected) and not failing and not blockers,'failing':failing,'provisional':provisional,'examined':len(selected),'blocking_findings':blockers}
