"""IMP2-16: reproducible unresolved RT pilot, never a historical interpretation.

build() requires an actual complete S1 ledger proven by a fresh import of the
caller's trusted run, ambiguity and mapping inputs, and rechecks every selected
source against the pinned source catalog. There is no unverified mode: `complete`
and validate_ledger() are claims a forged ledger can satisfy. Pass ambiguity=None
or mapping=None explicitly only when the trusted import used none. It does not
update a registry or its catalogs.
"""
from __future__ import annotations
import copy
import shutil
from pathlib import Path
from . import canon, ledger, sources

class PilotError(ValueError):
    pass

_UNSET=object()

def build(ledger_obj, source_catalog, source_roots, namespace_catalog, *, run=None, ambiguity=_UNSET, mapping=_UNSET):
    if run is None: raise PilotError('pilot requires the trusted run input; an unverified ledger cannot produce a decision')
    if ambiguity is _UNSET or mapping is _UNSET: raise PilotError('pilot requires explicit trusted ambiguity and mapping inputs (None only if the import used none)')
    errors=ledger.validate_ledger(ledger_obj)
    if any(f.cls=='DATA_ERROR' for f in errors) or not ledger_obj.get('complete'):
        raise PilotError('pilot requires a complete valid ledger')
    entries=ledger_obj['entries']
    if not isinstance(namespace_catalog,dict) or not isinstance(namespace_catalog.get('namespaces'),list):
        raise PilotError('pilot requires a usable namespace catalog with a namespaces list')
    spaces={n.get('key') for n in namespace_catalog.get('namespaces',[]) if isinstance(n,dict)}
    ns='micromap-resolver-gaps'
    if ns not in spaces: raise PilotError('resolver namespace is absent; no namespace is invented')
    try:
        ledger.require_rebuild_match(ledger_obj,run,source_catalog,namespace_catalog,ambiguity,mapping,source_roots)
    except ledger.RebuildMismatch as exc:
        raise PilotError(f'ledger is not the import of the trusted inputs: {exc}') from exc
    except (ledger.LedgerInputError,sources.SourceError) as exc:
        raise PilotError(f'ledger cannot be verified against the trusted inputs: {exc}') from exc
    selected={}
    for label in ('RT1','RT3'):
        candidates=[e for e in entries if e.get('class')=='LABEL' and e.get('text')==label and e.get('namespace')==ns and e.get('version')=='ratified-bytes' and 'line' in e]
        if not candidates: raise PilotError('no unambiguous literal ledger occurrence of '+label)
        selected[label]=sorted(candidates,key=lambda e:(e['source'],e['line'],e['column']))[0]
    ranges=[e for e in entries if e.get('class')=='RANGE' and e.get('ends')==['RT1','RT3'] and e.get('text') in ('RT1–RT3','RT1-RT3') and e.get('version')=='ratified-bytes' and 'line' in e]
    if not ranges: raise PilotError('no RT1–RT3 range in the ledger')
    selected['RT2']=sorted(ranges,key=lambda e:(e['source'],e['line'],e['column']))[0]
    if any(e.get('class')=='LABEL' and e.get('text')=='RT2' for e in entries):
        raise PilotError('RT2 literal occurrence requires owner review; pilot assumption changed')
    records={}
    searched=sorted({(e.get('source'),e.get('version'),e.get('sha256')) for e in entries if e.get('source')})
    for n in (1,2,3):
        label=f'RT{n}';e=selected[label]
        data=sources.read_verified(source_catalog,source_roots,e['source'],e['version'])
        version=sources.find_version(source_catalog,e['source'],e['version'])
        if version['sha256']!=e['sha256']: raise PilotError('ledger/source identity differs')
        lines=data.decode('utf-8').splitlines()
        try: line=lines[e['line']-1]
        except IndexError: raise PilotError('ledger line no longer exists') from None
        if line[e['column']-1:e['column']-1+e['length']]!=e['text']:
            raise PilotError('ledger location does not match the pinned source')
        ref={'source':e['source'],'version':e['version'],'anchor':e['unit'],'fragment':label,'quote':line}
        alias={'namespace':ns,'value':label,'status':'ACTIVE' if n!=2 else 'IMPLIED_BY_RANGE','source':copy.deepcopy(ref)}
        if n==2: alias['range_source']={'source':e['source'],'version':e['version'],'quote':e['text']}
        rid=f'CLX-REQ-{n:04d}'
        r={'schema_version':1,'id':rid,'type':'REQ','title':label+' — unresolved historical resolver gap',
           'kind':'test-obligation','statement':label,'statement_origin':'derived-from-range' if n==2 else 'quoted',
           'lifecycle':'ACTIVE','definition':'UNRESOLVED','definition_note':'No located source defines the item, expected result or meaning of killed. Searched pinned versions: '+repr(searched),
           'persistence':'UNSPECIFIED','ratification':{'state':'RATIFIED','source':copy.deepcopy(ref)},
           'origin':ref,'aliases':[alias],'ms_ref':'M3d','applies_to':{'platforms':['windows','linux']},
           'acceptance':[{'id':'AC-1','kind':'evidence','resolved':False,'text':'Definition and observable acceptance remain unresolved.'}],
           'open_questions':[{'text':'TD-10: owner must define, replace or withdraw this historical item.'}],
           'revision':1,'revisions':[],
           'note':'Pilot only. Historical R1/R3 occurrences remain ambiguous across namespaces (TD-9); no historical meaning or mutant binding is inferred. AUDIT-C runner mutants are explicitly excluded from RT evidence; no alias is fabricated from an uncatalogued source.'}
        r['revisions']=[{'n':1,'digest':canon.normative_digest(r),'change_class':'INITIAL'}]
        records[rid]=r
    return records

def write(out_dir, records):
    """Write into a new candidate directory; refuses any preexisting directory."""
    out=Path(out_dir)
    if out.exists(): raise PilotError('pilot output already exists')
    out.mkdir()
    try:
        for rid,r in sorted(records.items()):
            target=out/'records'/r['type']/(rid+'.json')
            target.parent.mkdir(parents=True,exist_ok=True)
            canon.write_record(target,r)
    except BaseException:
        # Only this invocation's newly created directory is eligible for cleanup.
        shutil.rmtree(out)
        raise
    return out
