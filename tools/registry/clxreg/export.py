"""Deterministic, read-only roadmap views (IMP2-17/18).

The optional mapping names an ODS sheet and an exact literal row-id cell; it
never infers identity from an alias and never edits the input spreadsheet.
"""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from . import canon, ledger, units


class ExportError(ValueError):
    pass


OFFICE = 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'
TABLE = 'urn:oasis:names:tc:opendocument:xmlns:table:1.0'
TEXT = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
for prefix, uri in (('office', OFFICE), ('table', TABLE), ('text', TEXT)):
    ET.register_namespace(prefix, uri)


def _records(model):
    if not isinstance(model, dict) or model.get('schema') != 'model/1':
        raise ExportError('export requires model/1')
    records = model.get('records')
    if not isinstance(records, list) or any(not isinstance(r, dict) or not isinstance(r.get('id'), str) for r in records):
        raise ExportError('model records must be a list of identified objects')
    if len({r['id'] for r in records}) != len(records):
        raise ExportError('duplicate model record ids')
    return sorted(records, key=lambda r: r['id'])


def _ods_rows(path):
    path = Path(path)
    before = path.read_bytes()
    read = units.read_units('.ods', before)
    after = path.read_bytes()
    if before != after:
        raise ExportError('ODS changed during reading')
    by_id = {}
    for unit in read:
        # The sheet may itself contain ! or R; anchor from the right.
        m = re.fullmatch(r'(.*)!R([0-9]+)C([0-9]+)/p[0-9]+', unit.id)
        if m:
            by_id.setdefault((m.group(1), unit.text), set()).add(int(m.group(2)))
    return by_id, hashlib.sha256(before).hexdigest()


def _mapping(mapping, records, ods_path):
    if mapping is None:
        return {}, [], ''
    if not isinstance(mapping, dict) or mapping.get('schema') != 'clx.roadmap-mapping/1' or not isinstance(mapping.get('rows'), list):
        raise ExportError('mapping must be clx.roadmap-mapping/1 with rows')
    known = {r['id'] for r in records}
    if ods_path is None:
        raise ExportError('an ODS input is required when a mapping is supplied')
    ods, digest = _ods_rows(ods_path)
    mapped, findings = {}, []
    for row in mapping['rows']:
        if not isinstance(row, dict) or set(row) != {'record', 'sheet', 'row_id'} or any(not isinstance(row.get(k), str) or not row[k] for k in row):
            raise ExportError('mapping rows require record, sheet and exact literal row_id')
        rid = row['record']
        if rid not in known:
            raise ExportError(f'mapping references unknown record {rid}')
        if rid in mapped:
            raise ExportError(f'duplicate mapping for {rid}')
        found = sorted(ods.get((row['sheet'], row['row_id']), ()))
        if len(found) != 1:
            message = 'ODS row not found' if not found else 'ODS row id is ambiguous'
            findings.append({'record': rid, 'message': message, 'sheet': row['sheet'], 'row_id': row['row_id']})
        mapped[rid] = (row['sheet'], row['row_id'], str(found[0]) if len(found) == 1 else '')
    return mapped, sorted(findings, key=lambda f: (f['record'], f['message'])), digest


def tables(model, *, registry_commit, import_ledger=None, mapping=None, ods_path=None):
    """Return every sheet as rows of strings, with all import occurrences visible."""
    if not isinstance(registry_commit, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', registry_commit):
        raise ExportError('registry_commit must be an explicit full commit hash')
    records = _records(model)
    mapped, findings, ods_digest = _mapping(mapping, records, ods_path)
    derived = model.get('derived', {})
    if not isinstance(derived, dict):
        raise ExportError('model derived must be an object')
    roadmap = [['id', 'title', 'type', 'verification', 'effective_status', 'asserted_status', 'drift', 'ods_sheet', 'ods_row_id', 'ods_row']]
    for r in records:
        state = derived.get(r['id'], {})
        asserted = sorted({str(x.get('status')) for x in r.get('asserted_status', []) if isinstance(x, dict) and x.get('status')})
        effective = str(state.get('effective_status', ''))
        drift = 'CLAIM_DIFFERS' if asserted and any(s != effective for s in asserted) else ''
        roadmap.append([r['id'], str(r.get('title', '')), str(r.get('type', '')), str(state.get('verification', '')), effective, ', '.join(asserted), drift, *mapped.get(r['id'], ('', '', ''))])
    summary = [['source', 'version', 'disposition', 'count']]
    detail = [['source', 'version', 'disposition', 'unit', 'column', 'text', 'record']]
    total = 0
    if import_ledger is not None:
        invalid = ledger.validate_ledger(import_ledger)
        if invalid:
            raise ExportError('invalid ledger: ' + '; '.join(f.line() for f in invalid))
        entries = import_ledger['entries']
        counts = {}
        for e in sorted(entries, key=canon.dumps_compact):
            key = (e['source'], e['version'], e['disposition'])
            counts[key] = counts.get(key, 0) + 1
            detail.append([str(e.get(k, '')) for k in ('source', 'version', 'disposition', 'unit', 'column', 'text', 'record')])
        for key, count in sorted(counts.items()):
            summary.append([*key, str(count)])
        total = len(entries)
    metadata = [['key', 'value'], ['schema version', 'model/1'], ['registry commit', registry_commit],
                ['registry_commit_role', 'reference baseline; clean-tree binding not asserted'],
                ['registry_records_sha256', canon.digest(records)],
                ['import_ledger_sha256', canon.digest(import_ledger) if import_ledger is not None else ''],
                ['ODS sha256', ods_digest], ['ledger occurrences', str(total)]]
    return {'REGISTRY-METADATA': metadata, 'REGISTRY-ROADMAP': roadmap,
            'REGISTRY-COVERAGE-OF-IMPORT': summary, 'REGISTRY-IMPORT-OCCURRENCES': detail,
            'REGISTRY-EXPORT-FINDINGS': [['record', 'message', 'sheet', 'row_id']] + [[f[k] for k in ('record', 'message', 'sheet', 'row_id')] for f in findings]}


def tsv(sheet_tables):
    """One TSV with explicit sheet markers; csv quoting preserves tabs/newlines."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    for name, rows in sheet_tables.items():
        writer.writerow(['# sheet', name])
        writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def fods(sheet_tables):
    root = ET.Element(f'{{{OFFICE}}}document', {f'{{{OFFICE}}}mimetype': 'application/vnd.oasis.opendocument.spreadsheet', f'{{{OFFICE}}}version': '1.2'})
    body = ET.SubElement(root, f'{{{OFFICE}}}body')
    spreadsheet = ET.SubElement(body, f'{{{OFFICE}}}spreadsheet')
    for name, rows in sheet_tables.items():
        table = ET.SubElement(spreadsheet, f'{{{TABLE}}}table', {f'{{{TABLE}}}name': name})
        for row in rows:
            tr = ET.SubElement(table, f'{{{TABLE}}}table-row')
            for value in row:
                cell = ET.SubElement(tr, f'{{{TABLE}}}table-cell', {f'{{{OFFICE}}}value-type': 'string'})
                # Preserve XML whitespace through text:s/tab/line-break elements.
                p = ET.SubElement(cell, f'{{{TEXT}}}p')
                value = str(value)
                if any(not (c in '\t\n\r' or '\x20' <= c <= '\ud7ff' or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff') for c in value):
                    raise ExportError('cell contains a character not representable in XML 1.0')
                pieces = re.split(r'( +|\t|\n)', value)
                last = None
                for piece in pieces:
                    if not piece:
                        continue
                    if piece.startswith(' '):
                        last = ET.SubElement(p, f'{{{TEXT}}}s', {f'{{{TEXT}}}c': str(len(piece))})
                    elif piece == '\t':
                        last = ET.SubElement(p, f'{{{TEXT}}}tab')
                    elif piece == '\n':
                        last = ET.SubElement(p, f'{{{TEXT}}}line-break')
                    elif last is None:
                        p.text = (p.text or '') + piece
                    else:
                        last.tail = (last.tail or '') + piece
    # A raw CR in XML text would be normalized to LF by the reader.
    return ET.tostring(root, encoding='utf-8', xml_declaration=True).replace(b'\r', b'&#13;') + b'\n'


def write(path, model, *, registry_commit, import_ledger=None, mapping=None, ods_path=None):
    """Create a new .fods/.tsv view. Output never replaces an existing path."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f'refusing to overwrite {path}')
    if ods_path is not None and path.resolve() == Path(ods_path).resolve():
        raise ExportError('output must not be the input ODS')
    sheet_tables = tables(model, registry_commit=registry_commit, import_ledger=import_ledger, mapping=mapping, ods_path=ods_path)
    if path.suffix.lower() not in ('.fods', '.tsv'):
        raise ExportError('export extension must be .fods or .tsv')
    data = fods(sheet_tables) if path.suffix.lower() == '.fods' else tsv(sheet_tables)
    with path.open('xb') as fh:
        fh.write(data)
    return {'sha256': hashlib.sha256(data).hexdigest(), 'sheets': list(sheet_tables),
            'findings': sheet_tables['REGISTRY-EXPORT-FINDINGS'][1:]}
