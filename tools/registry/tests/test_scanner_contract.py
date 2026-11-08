"""Real zero-width scanner failures stay typed and cannot hang a test runner."""
import subprocess
import sys
import unittest


class ScannerGuardTests(unittest.TestCase):
    def run_scanner_child(self, script):
        try:
            child = subprocess.run(
                [sys.executable, '-B', '-X', 'utf8', '-c', script],
                capture_output=True, text=True, encoding='utf8', timeout=3,
            )
        except subprocess.TimeoutExpired:
            self.fail('scanner did not reject its zero-width match within 3 seconds')
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_conditional_empty_match_is_rejected_with_a_typed_offset(self):
        # Unlike an empty-matching regex, this compiles successfully and fails
        # only when the scanner sees a matching character in actual source text.
        self.run_scanner_child('''
from clxreg import patterns
from tests.test_patterns import catalog
namespaces = catalog()
namespaces['namespaces'][0]['label_pattern'] = r'RT[0-9]+|(?<=1)$'
compiled = patterns.compile_namespaces(namespaces)
assert patterns.scan_text('RT2', compiled)[0].text == 'RT2'
try:
    patterns.scan_text('RT1', compiled)
except patterns.ZeroWidthMatch as error:
    assert error.offset == 3
else:
    raise AssertionError('an empty match was accepted')
''')

    def test_guard_rejects_empty_matches_before_advancing_at_end_of_input(self):
        # Runs the potentially looping call in a bounded child process. A
        # removed guard leaves pos == len(text), so search keeps finding '$'.
        script = '''
import re
from clxreg import patterns
try:
    patterns.boundary_matches(re.compile(r'$'), 'RT1')
except patterns.ZeroWidthMatch as error:
    assert error.offset == 3
else:
    raise AssertionError('an empty match was accepted')
'''
        self.run_scanner_child(script)


    def test_real_scanner_error_is_converted_to_ledger_input_error(self):
        # This namespace is valid on empty text; only the real source scan
        # encounters its zero-width alternative. No scanner mock is involved.
        self.run_scanner_child('''
from clxreg import ledger, patterns
from tests.test_ledger import Fx
fixture = Fx()
fixture.setUp()
try:
    fixture.ns['namespaces'][0]['label_pattern'] = r'RT[0-9]+|(?<=g)$'
    try:
        fixture.build()
    except ledger.LedgerInputError as error:
        assert isinstance(error.__cause__, patterns.ZeroWidthMatch)
        assert 'doc/v1' in str(error)
        assert 'unit L1' in str(error)
        assert 'zero-width regular expression match' not in str(error)
    else:
        raise AssertionError('an empty match was accepted')
finally:
    fixture.doCleanups()
''')


if __name__ == '__main__':
    unittest.main()
