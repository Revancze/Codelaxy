"""Malformed inputs and incomplete inventories never produce quiet success."""
import copy
import io
from contextlib import redirect_stdout, redirect_stderr
from clxreg import canon, cli, ledger
from tests.test_ledger import Fx


class LedgerCliContractTests(Fx):
    def paths(self, value=None, catalog=None):
        led, cat = self.d / 'ledger.json', self.d / 'sources.json'
        canon.write_record(led, self.build() if value is None else value, overwrite=True)
        canon.write_record(cat, self.src if catalog is None else catalog, overwrite=True)
        return led, cat

    def call(self, function, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = function(args)
        return code, out.getvalue(), err.getvalue()

    def verify_calls(self, led, cat):
        return ((ledger.main, ['verify', '--ledger', str(led), '--catalog', str(cat), '--root', 'ws=' + str(self.ws)]),
                (cli.main, ['ledger', 'verify', '--ledger', str(led), '--catalog', str(cat), '--source-root', 'ws=' + str(self.ws)]))

    def test_malformed_diff_inputs_are_refused_by_both_clis(self):
        good = self.build()
        entry = copy.deepcopy(good); del entry['entries'][0]['unit']
        row = copy.deepcopy(good); del row['sources'][0]['version']
        for bad in ([], entry, row):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ledger.LedgerInputError, 'invalid before ledger'):
                    ledger.diff_ledgers(bad, good)
                before, after = self.d / 'before.json', self.d / 'after.json'
                canon.write_record(before, bad, overwrite=True); canon.write_record(after, good, overwrite=True)
                for function, args, expected in ((ledger.main, ['diff', str(before), str(after)], 3),
                                                (cli.main, ['ledger-diff', str(before), str(after)], 1)):
                    code, out, err = self.call(function, args)
                    self.assertEqual(code, expected, (out, err))
                    self.assertIn('invalid before ledger', err)
                    self.assertNotIn('Traceback', err)

    def test_catalog_shape_is_checked_before_reading_locations(self):
        bad = copy.deepcopy(self.src); del bad['sources'][0]['versions'][0]['location']
        led, cat = self.paths(catalog=bad)
        findings = ledger.verify_ledger(self.build(), bad, self.roots)
        self.assertTrue(any(f.code == 'DE-02' and 'location' in f.message for f in findings))
        run, namespaces = self.d / 'run.json', self.d / 'namespaces.json'
        canon.write_record(run, self.run); canon.write_record(namespaces, self.ns)
        proof = ['--run', str(run), '--namespaces', str(namespaces)]
        # Malformed ledger and malformed catalog remain data errors even when a
        # valid trusted rebuild was requested: neither is proof of tampering.
        for value, catalog in ((self.build(), bad), ([], self.src)):
            led, cat = self.paths(value=value, catalog=catalog)
            for function, args in self.verify_calls(led, cat):
                for suffix in ([], proof):
                    code, out, err = self.call(function, args + suffix)
                    self.assertEqual(code, 1, (out, err))
                    self.assertNotIn('fresh import', out)
                    self.assertNotIn('Traceback', err)

    def test_problem_source_requires_a_recorded_problem(self):
        (self.ws / 'b.md').write_bytes(b'changed')
        bad = self.build(); bad['problems'] = []
        for findings in (ledger.validate_ledger(bad), ledger.verify_ledger(bad, self.src, self.roots)):
            self.assertTrue(any('PROBLEM source requires a recorded problem' in f.message for f in findings))

    def test_incomplete_inventory_is_explicit_and_never_exit_zero(self):
        (self.ws / 'b.md').unlink()
        value = self.build(); led, cat = self.paths(value=value)
        findings = ledger.verify_ledger(value, self.src, self.roots)
        self.assertTrue(any(f.code == 'AD-04' and 'MISSING' in f.message for f in findings))
        for (function, args), expected in zip(self.verify_calls(led, cat), (2, 4)):
            code, out, err = self.call(function, args)
            self.assertEqual(code, expected, (out, err))
            self.assertIn('incomplete', out.lower())
        self.assertIn('verify: INCOMPLETE', self.call(*self.verify_calls(led, cat)[0])[1])

    def test_unavailable_processed_source_is_not_a_success(self):
        led, cat = self.paths(); (self.ws / 'b.md').unlink()
        for (function, args), expected in zip(self.verify_calls(led, cat), (2, 4)):
            code, out, err = self.call(function, args)
            self.assertEqual(code, expected, (out, err))
            self.assertIn('AD-04', out)

    def test_each_structural_finding_is_reported_once(self):
        value = self.build(); value['entries'][0]['column'] = 0
        led, cat = self.paths(value=value)
        expected = ledger.validate_ledger(value)
        for function, args in self.verify_calls(led, cat):
            code, out, err = self.call(function, args)
            self.assertEqual(code, 1, (out, err))
            for finding in expected:
                self.assertEqual(out.count(finding.line()), 1, out)

    def test_changed_source_has_its_own_diff_format(self):
        (self.ws / 'b.md').unlink()
        before = self.build(); after = copy.deepcopy(before)
        next(e for e in after['entries'] if e['class'] == 'SOURCE')['reason'] = 'more precise reason'
        a, b = self.d / 'a.json', self.d / 'b.json'
        canon.write_record(a, before); canon.write_record(b, after)
        code, out, err = self.call(ledger.main, ['diff', str(a), str(b)])
        self.assertEqual(code, 1, err)
        self.assertIn('changed  doc/v2 SOURCE:', out)
        self.assertNotIn('None col None', out)
        self.assertIn('more precise reason', out)
