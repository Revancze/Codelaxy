"""Portable honest ledgers and their forgeries (not a test module).

Each forgery keeps the ledger structurally valid, so only a rebuild from trusted
inputs can tell it from the honest one.
"""
import copy
import hashlib
from pathlib import Path

from clxreg import ledger, sources
from tests.test_patterns import catalog as ns_catalog

RESOLVER = 'micromap-resolver-gaps'
AUTHORITY = b'x\n'
RATIFIED = 'RT1–RT3 is the range; RT1 here and RT3 there.\n'.encode('utf-8')
CLEAN = 'Q99 and F11 here, also R1 twice.\n'.encode('utf-8')
WITH_RT2 = 'RT2 and Q99 here.\n'.encode('utf-8')
AMBIGUOUS_RT1 = {'schema': 'clx.ambiguity/1', 'rules': [{'namespace': RESOLVER, 'value': 'RT1', 'meanings': ['a', 'b'], 'basis': 'doc'}]}


def _version(vid, name, data):
    return {'id': vid, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'pinning': 'sha256-only', 'status': 'DRAFT', 'location': {'root': 'ws', 'path': name}}


class Scenario:
    def __init__(self, directory, second=CLEAN, ambiguity=None, mapping=None):
        self.ws = Path(directory) / 'ws'
        self.ws.mkdir()
        files = {'x.md': AUTHORITY, 'a.md': RATIFIED, 'b.md': second}
        for name, data in files.items():
            (self.ws / name).write_bytes(data)
        self.src = {'schema': sources.SCHEMA, 'sources': [{'key': 'doc', 'title': 'D', 'category': 'DRAFT', 'versions': [
            _version('v1', 'x.md', AUTHORITY), _version('ratified-bytes', 'a.md', RATIFIED), _version('v2', 'b.md', second)]}]}
        self.ns = ns_catalog()
        self.roots = {'ws': str(self.ws)}
        self.run = {'schema': ledger.RUN_SCHEMA, 'include': [{'source': 'doc', 'version': 'ratified-bytes'}, {'source': 'doc', 'version': 'v2'}], 'excluded': []}
        self.ambiguity = ambiguity
        self.mapping = mapping

    def honest(self):
        return ledger.build_ledger(self.run, self.src, self.ns, self.ambiguity, self.mapping, self.roots)

    def pilot_inputs(self):
        return {'run': self.run, 'ambiguity': self.ambiguity, 'mapping': self.mapping}

    def export_inputs(self):
        return {'run': self.run, 'catalog': self.src, 'namespaces': self.ns, 'ambiguity': self.ambiguity, 'mapping': self.mapping, 'roots': self.roots}


def recount(led):
    dispositions, classes = {}, {}
    for n, entry in enumerate(led['entries'], 1):
        entry['n'] = n
        dispositions[entry['disposition']] = dispositions.get(entry['disposition'], 0) + 1
        classes[entry['class']] = classes.get(entry['class'], 0) + 1
    led['summary'] = {'entries': len(led['entries']), 'sources': len(led['sources']), 'dispositions': dispositions, 'classes': classes}
    return led


def _second_source_as(led, status, disposition, **extra):
    forged = copy.deepcopy(led)
    row = forged['sources'][1]
    forged['entries'] = [e for e in forged['entries'] if e['version'] != 'v2']
    if disposition:
        forged['entries'].append({'class': 'SOURCE', 'disposition': disposition, 'source': 'doc', 'version': 'v2', 'sha256': row['sha256'], 'reason': 'forged', **extra})
    forged['sources'][1] = {k: row[k] for k in ('source', 'version', 'sha256')} | {'status': status}
    forged['complete'] = status == 'EXCLUDED'
    return recount(forged)


def k1_processed_to_excluded(led):
    return _second_source_as(led, 'EXCLUDED', 'EXCLUDED', decision='forged')


def k2_drop_rt2(led):
    forged = copy.deepcopy(led)
    forged['entries'] = [e for e in forged['entries'] if not (e['class'] == 'LABEL' and e.get('text') == 'RT2')]
    return recount(forged)


def k3_problem_without_problems(led):
    return _second_source_as(led, 'PROBLEM', None)


def k4_processed_to_missing(led):
    return _second_source_as(led, 'MISSING', 'SOURCE_MISSING')


def k5_fabricated_alias(led):
    forged = copy.deepcopy(led)
    entry = next(e for e in forged['entries'] if e['disposition'] == 'NOT_MIGRATED' and e.get('text') == 'RT3')
    entry.update(disposition='MIGRATED_AS_ALIAS', record='CLX-REQ-0001', status='ACTIVE')
    return recount(forged)


def k6_erase_ambiguity(led, text='RT1', namespace=RESOLVER):
    forged = copy.deepcopy(led)
    for entry in forged['entries']:
        if entry.get('text') == text and entry['disposition'] == 'AMBIGUOUS':
            entry.pop('candidates')
            entry.pop('meanings', None)
            entry.update(disposition='NOT_MIGRATED', namespace=namespace)
    return recount(forged)


def k7_omit_source(led):
    forged = copy.deepcopy(led)
    forged['entries'] = [e for e in forged['entries'] if e['version'] != 'v2']
    forged['sources'] = forged['sources'][:1]
    return recount(forged)
