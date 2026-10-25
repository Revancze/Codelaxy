"""Negative tests: break the code on purpose and require the matching invariant test to go RED.

Each mutation is applied to a throw-away COPY of the tool; the real files are never touched.
Run:  python -B -m unittest test_mutations      (slow: runs the browser tests inside each copy)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import roadmap_view as rv

HERE = Path(__file__).resolve().parent
T = "test_roadmap_view."

# (name, file, old, new, tests that must fail)
MUTATIONS = [
    ("html escaping removed", "rv_html.py", "return html.escape(s, quote=True)", "return s",
     [T + "HostileContent.test_workbook_text_is_escaped_never_html"]),
    ("javascript: links allowed", "rv_html.py", 'SAFE_WEB = re.compile(r"^https?://',
     'SAFE_WEB = re.compile(r"^[A-Za-z]+:', [T + "HostileContent.test_only_http_and_internal_hrefs_become_links"]),
    ("CSP allows the network", "rv_html.py", "connect-src 'none'", "connect-src *",
     [T + "HostileContent.test_csp_forbids_network_access_from_scripts", T + "HostileContent.test_the_browser_really_enforces_that_policy"]),
    ("hash ignores normalisation", "rv_text.py", "return hashlib.sha256(normalize(text).encode", "return hashlib.sha256(text.encode",
     [T + "TranslationBinding.test_hash_is_stable_across_newline_and_unicode_forms"]),
    ("translation check disabled", "rv_text.py", "    problems = []\n    if en.count", "    return []\n    if en.count",
     [T + "TranslationBinding.test_a_damaged_translation_is_refused", T + "ProtectedTokens.test_czech_pack_keeps_every_protected_token"]),
    ("nothing is protected", "rv_text.py", "    spans.sort()\n    merged", "    spans = []\n    merged",
     [T + "ProtectedTokens.test_identifiers_statuses_files_and_hashes_are_protected_structurally",
      T + "ProtectedTokens.test_translator_receives_placeholders_not_the_protected_text"]),
    ("ODS change goes unnoticed", "roadmap_view.py", "    if after != (sha, blob):", "    if False:",
     [T + "OriginalIntegrity.test_a_changed_ods_during_the_run_aborts"]),
    ("generation timestamp in output", "rv_html.py", '<meta name="rv-generator" content="{GENERATOR}">',
     '<meta name="rv-generator" content="{GENERATOR}"><!--{__import__("time").time()}-->',
     [T + "Determinism.test_same_inputs_give_identical_output"]),
    ("outdated translation still shown", "viewer.js", "if (e[0] !== h) return Promise.resolve({ kind: 'outdated' });", "",
     [T + "BrowserFromDisk.test_changed_english_marks_the_old_translation_outdated_never_shows_it"]),
    ("missing translation not handled", "viewer.js", "if (!e) return Promise.resolve({ kind: 'missing' });", "",
     [T + "BrowserFromDisk.test_missing_translation_for_a_cell_falls_back_to_english"]),
    ("absent Translator API breaks the page", "viewer.js",
     "{ setCells(false); setStatus(ui.status_api_missing); return Promise.resolve(); }", "{ throw new Error('no translator'); }",
     [T + "BrowserFromDisk.test_unavailable_translator_never_blocks_reading"]),
    ("watcher does not wait for a save to settle", "roadmap_view.py", "        if sig != self.seen_sig:  # just changed", "        if False:  # just changed",
     [T + "LiveUpdate.test_a_save_triggers_one_rebuild_after_the_file_settles"]),
    ("watcher dies on a half-written file", "roadmap_view.py",
     "except (OSError, ValueError, KeyError, SystemExit, zipfile.BadZipFile, ET.ParseError) as e:", "except ZeroDivisionError as e:",
     [T + "LiveUpdate.test_half_written_file_is_retried_not_fatal"]),
    ("storage access can throw", "viewer.js", "function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }",
     "function load(k) { return localStorage.getItem(k); }", [T + "BrowserFromDisk.test_storage_that_throws_does_not_break_the_page"]),
    ("invalid language code accepted", "viewer.js", "var ready = setLang(CODE_RE.test(wanted) ? wanted : 'en', false);",
     "var ready = setLang(wanted, false);", [T + "BrowserFromDisk.test_an_invalid_language_code_is_ignored_safely"]),
]


class Mutations(unittest.TestCase):
    def run_mutation(self, name, filename, old, new, tests):
        with tempfile.TemporaryDirectory(prefix="rv-mut-") as tmp:
            work = Path(tmp)
            for p in HERE.glob("*.py"):
                shutil.copy2(p, work / p.name)
            for p in (HERE / "viewer.js", HERE / "viewer.css"):
                shutil.copy2(p, work / p.name)
            (work / "input").mkdir()
            shutil.copyfile(rv.DEFAULT_ODS, work / "input" / "Codelaxy-Roadmap.ods")
            shutil.copytree(HERE / "lang", work / "lang", ignore=shutil.ignore_patterns("chunks"))
            target = work / filename
            text = target.read_text(encoding="utf-8")
            self.assertEqual(text.count(old), 1, f"mutation '{name}' does not apply exactly once")
            target.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
            ok = subprocess.run([sys.executable, "-B", "-m", "unittest", *tests], cwd=work, capture_output=True, text=True)
            self.assertNotEqual(ok.returncode, 0, f"mutation '{name}' was NOT caught:\n{ok.stdout[-800:]}{ok.stderr[-800:]}")

    def test_every_mutation_turns_an_invariant_red(self):
        for name, filename, old, new, tests in MUTATIONS:
            with self.subTest(mutation=name):
                self.run_mutation(name, filename, old, new, tests)

    def test_unmutated_copy_is_green(self):
        """Control: without a mutation the same tests pass, so a RED above is caused by the mutation."""
        with tempfile.TemporaryDirectory(prefix="rv-mut-") as tmp:
            work = Path(tmp)
            for p in list(HERE.glob("*.py")) + [HERE / "viewer.js", HERE / "viewer.css"]:
                shutil.copy2(p, work / p.name)
            (work / "input").mkdir()
            shutil.copyfile(rv.DEFAULT_ODS, work / "input" / "Codelaxy-Roadmap.ods")
            shutil.copytree(HERE / "lang", work / "lang", ignore=shutil.ignore_patterns("chunks"))
            tests = sorted({t for m in MUTATIONS for t in m[4]})
            ok = subprocess.run([sys.executable, "-B", "-m", "unittest", *tests], cwd=work, capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout[-800:] + ok.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
