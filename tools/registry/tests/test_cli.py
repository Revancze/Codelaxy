"""IMP2-20: exit classes, input preservation, model contract and adapter isolation."""
import copy
import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import types
import unittest
import subprocess
from unittest import mock

from clxreg import canon, cli, sources
from tests.test_ledger import Fx


GOLDEN = Path(__file__).parent / 'data/model1-golden.json'
H = '227733484a1851bc512f7ba3fef6dd78b6d0e5da'


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'registry'
        self.root.mkdir()
        for typ in ('REQ', 'SCN', 'EVD', 'MIL'):
            (self.root / 'records' / typ).mkdir(parents=True)
        self.fixture = json.loads(GOLDEN.read_text(encoding='utf-8'))

    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['--registry-root', str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def stub(self, value=None, passed=False):
        # Stub only the validator boundary, not CLI classification or IO.
        mod = types.ModuleType('clxreg.validator')
        mod.check_root = lambda root, **kw: copy.deepcopy(self.fixture if value is None else value)
        mod.gate = lambda model, target=None: {'passed': passed and model['valid'], 'failing': [] if passed else ['CLX-REQ-0001']}
        import clxreg
        return mock.patch.object(clxreg, 'validator', mod, create=True)

    def fingerprint(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}

    def test_model1_golden_is_dumped_as_canonical_json_without_extra_authority(self):
        with self.stub():
            code, text, err = self.call(['dump-model'])
        self.assertEqual(code, 0)
        self.assertEqual(text, GOLDEN.read_text(encoding='utf-8'))
        self.assertEqual(err, '')
        self.assertEqual(json.loads(text)['schema'], 'model/1')

    def test_external_engine_cannot_change_state_gate_or_exit(self):
        path = Path(self.temp.name) / 'external.json'
        canon.write_record(path, [{'class': 'DATA_ERROR', 'code': 'INVENTED', 'verification': 'VERIFIED'}])
        with self.stub():
            baseline = self.call(['dump-model'])
            changed = self.call(['dump-model', '--external-findings', str(path)])
            gate = self.call(['gate', '--external-findings', str(path)])
        a, b = json.loads(baseline[1]), json.loads(changed[1])
        self.assertEqual(a['derived'], b['derived'])
        self.assertEqual(a['findings'], b['findings'])
        self.assertEqual((baseline[0], changed[0], gate[0]), (0, 0, 2))
        self.assertEqual(b['external_findings'][0]['code'], 'INVENTED')

    def test_table_of_check_and_gate_exit_codes(self):
        for model, expected_check, expected_gate in (
            (self.fixture, 0, 2),
            ({**self.fixture, 'valid': False, 'findings': [{'class': 'DATA_ERROR', 'code': 'DE-02', 'record': 'x', 'message': 'bad data'}]}, 1, 1),
            ({**self.fixture, 'findings': [{'class': 'ADVISORY', 'code': 'AD-04', 'record': 'sources:x', 'message': 'source file not available; checks skipped'}]}, 4, 4),
            ({**self.fixture, 'findings': [{'class': 'ADVISORY', 'code': 'AD-04', 'record': 'sources:x', 'message': 'pinning is sha256-only (outside git): the version is identified by its hash alone'}]}, 0, 2)):
            with self.subTest(expected_check=expected_check, findings=model['findings']), self.stub(model):
                self.assertEqual(self.call(['check'])[0], expected_check)
                self.assertEqual(self.call(['gate'])[0], expected_gate)

    def test_next_id_never_creates_a_record(self):
        (self.root / 'records/REQ/CLX-REQ-0007.json').write_text('{}', encoding='utf-8')
        before = self.fingerprint()
        code, text, _ = self.call(['next-id', 'REQ'])
        self.assertEqual((code, text.strip()), (0, 'CLX-REQ-0008'))
        self.assertEqual(self.fingerprint(), before)

    def test_export_writes_only_explicit_new_output_and_refuses_registry_output(self):
        output = Path(self.temp.name) / 'roadmap.tsv'
        before = self.fingerprint()
        with self.stub():
            self.assertEqual(self.call(['export', '--registry-commit', H, '--out', str(output)])[0], 0)
            self.assertEqual(self.call(['export', '--registry-commit', H, '--out', str(output)])[0], 3)
            self.assertEqual(self.call(['export', '--registry-commit', H, '--out', str(self.root / 'forbidden.tsv')])[0], 1)
            self.call(['check'])
            self.call(['gate'])
            self.call(['dump-model'])
        self.assertEqual(self.fingerprint(), before)
        self.assertFalse((self.root / 'forbidden.tsv').exists())

    def test_protect_uses_existing_baseline_and_names_a_mismatch(self):
        protected = Path(self.temp.name) / 'protected.txt'
        protected.write_bytes(b'original')
        manifest = Path(self.temp.name) / 'manifest.json'
        canon.write_record(manifest, {'schema': 1, 'roots': {'test': self.temp.name}, 'entries': [
            {'root': 'test', 'path': protected.name, 'sha256': hashlib.sha256(b'original').hexdigest()}]})
        before = manifest.read_bytes()
        self.assertEqual(self.call(['protect', '--manifest', str(manifest)])[0], 0)
        protected.write_bytes(b'changed')
        code, text, _ = self.call(['protect', '--manifest', str(manifest)])
        self.assertEqual(code, 4)
        self.assertIn('PR-02', text)
        self.assertEqual(manifest.read_bytes(), before)

    def test_missing_input_is_exit4_not_an_empty_success(self):
        self.assertEqual(self.call(['ledger-diff', str(self.root / 'missing.json'), str(self.root / 'also-missing.json')])[0], 4)

    def test_malformed_json_input_is_data_error_not_missing_source(self):
        path = Path(self.temp.name) / 'broken.json'
        path.write_text('{broken', encoding='utf-8')
        self.assertEqual(self.call(['ledger-diff', str(path), str(path)])[0], 1)

    def test_command_help_lists_public_commands(self):
        with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as e:
            cli.main(['--help'])
        self.assertEqual(e.exception.code, 0)
        for name in ('check', 'gate', 'next-id', 'ledger-diff', 'dump-model', 'export', 'protect'):
            self.assertIn(name, out.getvalue())


class LedgerCommandTests(Fx):
    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(['--registry-root', str(self.d / 'input-registry'), *args])
        return code, out.getvalue(), err.getvalue()

    def test_build_verify_diff_and_refusal_are_consistent_without_input_writes(self):
        catalog, ns, run, output = [self.d / name for name in ('sources.json', 'namespaces.json', 'run.json', 'ledger.json')]
        for path, value in ((catalog, self.src), (ns, self.ns), (run, self.run)):
            canon.write_record(path, value)
        inputs = {p: p.read_bytes() for p in (catalog, ns, run, *self.ws.iterdir())}
        build = ['ledger', 'build', '--catalog', str(catalog), '--namespaces', str(ns), '--run', str(run), '--source-root', 'ws='+str(self.ws), '--out', str(output)]
        self.assertEqual(self.call(build)[0], 0)
        self.assertEqual(self.call(build)[0], 3)
        self.assertEqual(self.call(['ledger', 'verify', '--catalog', str(catalog), '--source-root', 'ws='+str(self.ws), '--ledger', str(output)])[0], 0)
        self.assertEqual(self.call(['ledger-diff', str(output), str(output)])[0], 0)
        self.assertTrue(all(p.read_bytes() == value for p, value in inputs.items()))

    def test_tampered_source_does_not_return_success(self):
        catalog, ns, run, output = [self.d / name for name in ('sources.json', 'namespaces.json', 'run.json', 'ledger.json')]
        for path, value in ((catalog, self.src), (ns, self.ns), (run, self.run)):
            canon.write_record(path, value)
        (self.ws / 'a.md').write_bytes(b'tampered')
        args = ['ledger', 'build', '--catalog', str(catalog), '--namespaces', str(ns), '--run', str(run), '--source-root', 'ws='+str(self.ws), '--out', str(output)]
        code, _, _ = self.call(args)
        self.assertEqual(code, 4)


class ValidatorIntegrationTests(unittest.TestCase):
    def test_context_cannot_assert_continuous_freshness_without_git_proof(self):
        from tests.test_sources import FILES, good_catalog
        from tests.test_validator import complete_records
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            root = home / 'registry'
            root.mkdir()
            source_root = home / 'sources'
            source_root.mkdir()
            for name, data in FILES.items():
                (source_root / name).write_bytes(data)
            (source_root / 'artifact.txt').write_bytes(b'PASS\n')
            records = complete_records()
            records['CLX-REQ-0001']['persistence'] = 'CONTINUOUS'
            for record in records.values():
                path = root / 'records' / record['type'] / (record['id']+'.json')
                path.parent.mkdir(parents=True, exist_ok=True)
                canon.write_record(path, record)
            catalog_path, context_path = home / 'sources.json', home / 'context.json'
            canon.write_record(catalog_path, good_catalog())
            canon.write_record(context_path, {'freshness': {'CLX-EVD-0001': 'CURRENT'}})
            common = ['--catalog', str(catalog_path), '--source-root', 'ws='+str(source_root), '--artifact-root', str(source_root)]
            states = []
            for context_args in ([], ['--context', str(context_path)]):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = cli.main(['--registry-root', str(root), 'dump-model', *common, *context_args])
                self.assertEqual(code, 0, out.getvalue())
                state = json.loads(out.getvalue())['derived']['CLX-REQ-0001']
                self.assertNotEqual(state['verification'], 'VERIFIED')
                self.assertNotEqual(state['effective_status'], 'DONE')
                states.append(state)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(['--registry-root', str(root), 'gate', *common, *context_args]), 2)
            self.assertEqual(states[0], states[1])

    def test_actual_validator_matches_model1_golden_and_cli_remains_read_only(self):
        from clxreg import validator
        from tests.test_sources import FILES, good_catalog
        from tests.test_validator import complete_records
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            root = home / 'registry'
            root.mkdir()
            source_root = home / 'sources'
            source_root.mkdir()
            for name, data in FILES.items():
                (source_root / name).write_bytes(data)
            (source_root / 'artifact.txt').write_bytes(b'PASS\n')
            records = complete_records()
            for record in records.values():
                path = root / 'records' / record['type'] / (record['id']+'.json')
                path.parent.mkdir(parents=True, exist_ok=True)
                canon.write_record(path, record)
            catalog_path = home / 'sources.json'
            canon.write_record(catalog_path, good_catalog())
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(['--registry-root', str(root), 'dump-model', '--catalog', str(catalog_path), '--source-root', 'ws='+str(source_root), '--artifact-root', str(source_root)])
            self.assertEqual(code, 0, out.getvalue())
            self.assertEqual(out.getvalue(), GOLDEN.read_text(encoding='utf-8'))
            parsed = json.loads(out.getvalue())
            self.assertTrue(validator.gate(parsed)['passed'])
            self.assertEqual({p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
            # Actual Git status, not just an in-memory file map, stays unchanged.
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            def status():
                return subprocess.run(['git', '-C', str(root), '--no-optional-locks', 'status', '--porcelain=v1', '-uall'], check=True, capture_output=True).stdout
            original_status = status()
            common = ['--catalog', str(catalog_path), '--source-root', 'ws='+str(source_root), '--artifact-root', str(source_root)]
            for command in (['check', *common], ['gate', *common], ['dump-model', *common], ['next-id', 'REQ'], ['export', *common, '--registry-commit', H, '--out', str(home / 'actual.tsv')]):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(['--registry-root', str(root), *command]), 0)
                self.assertEqual(status(), original_status)
            (source_root / 'v2.md').write_bytes(b'tampered source')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--registry-root', str(root), 'check', *common]), 4)
            (source_root / 'v2.md').unlink()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--registry-root', str(root), 'check', *common]), 4)
            (source_root / 'v2.md').write_bytes(FILES['v2.md'])
            (source_root / 'artifact.txt').write_bytes(b'corrupted artifact')
            for command in ('check', 'gate', 'dump-model'):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(['--registry-root', str(root), command, *common]), 4)


if __name__ == '__main__':
    unittest.main()
