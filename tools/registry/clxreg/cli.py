"""IMP2-20: stdlib command line; only explicit outputs may be written."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import canon, export, ledger, protect, sources, store


def parser():
    ap = argparse.ArgumentParser(prog='registry', description='Read-only registry validation and explicit generated outputs. No Git mutations.')
    ap.add_argument('--registry-root', default='docs/registry', help='input registry directory; commands never write into it')
    sub = ap.add_subparsers(dest='command', required=True)
    for name in ('check', 'dump-model', 'gate', 'export'):
        p = sub.add_parser(name)
        # Allow the input root both before and after the command.
        p.add_argument('--registry-root', default=argparse.SUPPRESS)
        p.add_argument('--base', help='actual Git base ref for deletion, revision and alias checks')
        p.add_argument('--catalog', help='canonical sources catalog')
        p.add_argument('--namespaces', help='canonical namespaces catalog')
        p.add_argument('--source-root', action='append', default=[], metavar='NAME=PATH')
        p.add_argument('--context', help='canonical Git repo/ref and source-proven decision context; supplied verdicts/freshness maps have no authority')
        p.add_argument('--artifact-root', help='root for relative evidence artifact locators; defaults to --registry-root')
        p.add_argument('--min-records', type=int, default=1)
        p.add_argument('--external-findings', help='JSON list reported separately, never authoritative')
        if name == 'gate':
            p.add_argument('target', nargs='?', help='optional MIL/REQ identifier')
        if name == 'export':
            p.add_argument('--out', required=True, help='new .tsv or .fods file outside the input registry')
            p.add_argument('--registry-commit', required=True, help='explicit full baseline commit; does not claim a clean tree')
            p.add_argument('--ledger', help='canonical import ledger to include every disposition and occurrence')
            p.add_argument('--mapping', help='canonical clx.roadmap-mapping/1 mapping')
            p.add_argument('--ods', help='read-only source ODS; mandatory with mapping')
    p = sub.add_parser('next-id')
    p.add_argument('type', choices=store.STORED_TYPES)
    p.add_argument('--registry-root', default=argparse.SUPPRESS)
    p.add_argument('--base')
    p = sub.add_parser('ledger', help='build or verify an import ledger (explicit --out for build)')
    p.add_argument('--registry-root', default=argparse.SUPPRESS)
    p.add_argument('action', choices=('build', 'verify'))
    p.add_argument('--catalog', required=True)
    p.add_argument('--source-root', action='append', default=[], metavar='NAME=PATH')
    p.add_argument('--run')
    p.add_argument('--namespaces')
    p.add_argument('--ambiguity')
    p.add_argument('--mapping')
    p.add_argument('--out')
    p.add_argument('--ledger')
    p = sub.add_parser('ledger-diff')
    p.add_argument('--registry-root', default=argparse.SUPPRESS)
    p.add_argument('before')
    p.add_argument('after')
    p = sub.add_parser('protect', help='check the protected manifest and optional staged-state guard; never builds a new baseline')
    p.add_argument('--registry-root', default=argparse.SUPPRESS)
    p.add_argument('--manifest', required=True)
    p.add_argument('--repo')
    p.add_argument('--source-root', action='append', default=[])
    return ap


def _load(path, name):
    obj, findings = sources.load_canonical(path, name)
    if obj is None or findings:
        raise export.ExportError('; '.join(f.line() for f in findings))
    return obj


def _outside(path, root):
    output, source = Path(path).resolve(), Path(root).resolve()
    if output == source or source in output.parents:
        raise export.ExportError('output must be outside --registry-root')


def _model(args):
    from . import validator
    kw = {'min_records': args.min_records, 'source_roots': sources.parse_roots(args.source_root)}
    if args.catalog:
        kw['source_catalog'] = _load(args.catalog, 'sources')
    if args.namespaces:
        kw['namespace_catalog'] = _load(args.namespaces, 'namespaces')
    context = {}
    if args.context:
        context = _load(args.context, 'context')
        if not isinstance(context, dict):
            raise export.ExportError('context must be an object')
    if args.artifact_root:
        context['artifact_root'] = args.artifact_root
    elif 'artifact_root' not in context:
        context['artifact_root'] = args.registry_root
    kw['context'] = context
    model = validator.check_root(args.registry_root, base=args.base, **kw)
    external = _load(args.external_findings, 'external_findings') if args.external_findings else []
    if not isinstance(external, list):
        raise export.ExportError('external_findings must be a list')
    # Never supply external reports to the validator or change its valid/derived.
    model = dict(model)
    model['external_findings'] = external
    return model


def _data_exit(model):
    # Unavailable/tampered pinned sources are explicit failures of this execution.
    if any((f.get('code') == 'AD-04' and ('not available' in f.get('message', '') or 'skipped' in f.get('message', '')))
           or (f.get('code') == 'DE-13' and str(f.get('record', '')).startswith('sources:') and 'pinned version' in f.get('message', ''))
           or (f.get('code') == 'EM-04' and f.get('message', '').startswith('artifact could not be located and hash-verified:'))
           for f in model.get('findings', [])):
        return 4
    if any(f.get('class') == 'DATA_ERROR' for f in model.get('findings', [])):
        return 1
    return 0


def _print_findings(model):
    for finding in model.get('findings', []):
        print(f"{finding.get('class', ''):<16} {finding.get('code', ''):<6} {finding.get('record', '')}  {finding.get('message', '')}")
    print(f"examined {model.get('examined', 0)} records; valid={model.get('valid')}")
    if model.get('external_findings'):
        print('external_findings (non-authoritative): ' + canon.dumps_compact(model['external_findings']))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'protect':
            findings = protect.check(args.manifest, sources.parse_roots(args.source_root))
            if args.repo:
                findings += protect.check_staged(args.repo)
            for f in findings:
                print(f.line())
            print(f'protect: {len(findings)} findings')
            return 4 if any(f.code in ('PR-01', 'PR-02') for f in findings) else 1 if findings else 0
        if args.command == 'next-id':
            print(store.next_id(args.registry_root, args.type, args.base))
            return 0
        if args.command == 'ledger-diff':
            result = ledger.diff_ledgers(_load(args.before, 'ledger'), _load(args.after, 'ledger'))
            print(canon.dumps(result), end='')
            return 1 if any(result[k] for k in ('added', 'removed', 'changed', 'sources_changed')) else 0
        if args.command == 'ledger':
            roots = sources.parse_roots(args.source_root)
            catalog = _load(args.catalog, 'sources')
            if args.action == 'verify':
                if not args.ledger:
                    raise export.ExportError('ledger verify requires --ledger')
                value = _load(args.ledger, 'ledger')
                findings = ledger.validate_ledger(value) + ledger.verify_ledger(value, catalog, roots)
                if args.run:
                    if not args.namespaces:
                        raise export.ExportError('rebuild verification requires --namespaces')
                    findings += ledger.compare_with_rebuild(value, _load(args.run, 'run'), catalog, _load(args.namespaces, 'namespaces'), _load(args.ambiguity, 'ambiguity') if args.ambiguity else None, _load(args.mapping, 'mapping') if args.mapping else None, roots)
                for f in findings:
                    print(f.line())
                return 4 if any(f.code in ('DE-13', 'AD-04') for f in findings) else 1 if findings else 0
            if not (args.out and args.run and args.namespaces):
                raise export.ExportError('ledger build requires --out, --run and --namespaces')
            _outside(args.out, args.registry_root)
            if Path(args.out).exists():
                raise FileExistsError(f'refusing to overwrite {args.out}')
            value = ledger.build_ledger(_load(args.run, 'run'), catalog, _load(args.namespaces, 'namespaces'), _load(args.ambiguity, 'ambiguity') if args.ambiguity else None, _load(args.mapping, 'mapping') if args.mapping else None, roots)
            canon.write_record(args.out, value)
            print(f"ledger: {value['summary']['entries']} occurrences; complete={value['complete']}")
            return 4 if not value['complete'] or value['problems'] else 0
        model = _model(args)
        if args.command == 'dump-model':
            print(canon.dumps(model), end='')
            return _data_exit(model)
        if args.command == 'check':
            _print_findings(model)
            return _data_exit(model)
        if args.command == 'gate':
            from . import validator
            outcome = validator.gate(model, target=args.target)
            print(canon.dumps(outcome), end='')
            # Missing sources cannot be mistaken for an evaluated gate.
            status = _data_exit(model)
            return status if status else 0 if outcome['passed'] else 2
        if args.command == 'export':
            _outside(args.out, args.registry_root)
            result = export.write(args.out, model, registry_commit=args.registry_commit,
                                  import_ledger=_load(args.ledger, 'ledger') if args.ledger else None,
                                  mapping=_load(args.mapping, 'mapping') if args.mapping else None, ods_path=args.ods)
            print(canon.dumps(result), end='')
            return _data_exit(model)
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        return 3
    except (sources.SourceError, OSError) as e:
        print(f'registry: source unavailable or unreadable: {e}', file=sys.stderr)
        return 4
    except (store.StoreError, ledger.LedgerInputError, export.ExportError, canon.CanonError, ValueError) as e:
        print(f'registry: {e}', file=sys.stderr)
        return 1
    return 1


if __name__ == '__main__':
    sys.exit(main())
