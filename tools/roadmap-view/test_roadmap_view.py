"""Invariant tests for the roadmap viewer (translation layer).

Run:  python -B -m unittest test_roadmap_view          (browser tests are skipped without Chrome)
Each test proves a named invariant; test_mutations.py proves that breaking the code turns them RED.
"""

from __future__ import annotations

import builtins
import hashlib
import html.parser
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import roadmap_view as rv
import rv_html
import rv_ods
import rv_text

HERE = Path(__file__).resolve().parent
ODS = rv.DEFAULT_ODS
CHROME = next((c for c in (os.environ.get("CHROME", ""), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           "/usr/bin/google-chrome", "/usr/bin/chromium") if c and Path(c).exists()), None)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_files(files: dict[str, str], out: Path) -> None:
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text, encoding="utf-8", newline="\n")


def modified_ods(dst: Path, old: str, new: str) -> Path:
    """A COPY of the workbook with one text replaced (the original is only read)."""
    with zipfile.ZipFile(ODS) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "content.xml":
                text = data.decode("utf-8")
                assert text.count(old) >= 1, old
                data = text.replace(old, new, 1).encode("utf-8")
            zout.writestr(item, data)
    return dst


def synthetic_ods(dst: Path, cells: list[list[tuple[str, str | None]]]) -> Path:
    """A tiny hand-made ODS: rows of (text, href-or-None)."""
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:xlink="http://www.w3.org/1999/xlink"')
    rows = []
    for row in cells:
        tds = []
        for text, href in row:
            p = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if href:
                p = f'<text:a xlink:type="simple" xlink:href="{html.escape(href, quote=True)}">{p}</text:a>'
            tds.append(f'<table:table-cell office:value-type="string"><text:p>{p}</text:p></table:table-cell>')
        rows.append(f"<table:table-row>{''.join(tds)}</table:table-row>")
    width = max(len(r) for r in cells)
    content = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns}><office:body><office:spreadsheet>'
               f'<table:table table:name="OVERVIEW" table:print-ranges="OVERVIEW.A1:OVERVIEW.{chr(64 + width)}{len(cells)}">'
               f'<table:table-column table:number-columns-repeated="{width}"/>{"".join(rows)}</table:table>'
               f'</office:spreadsheet></office:body></office:document-content>')
    styles = f'<?xml version="1.0" encoding="UTF-8"?><office:document-styles {ns}><office:styles/></office:document-styles>'
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", content)
        z.writestr("styles.xml", styles)
    return dst


class CellText(html.parser.HTMLParser):
    """Map data-k -> visible text of every <td> in the generated page (what a reader sees)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells: dict[str, str] = {}
        self.attrs: dict[str, dict] = {}
        self._key = None
        self.tags: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        a = dict(attrs)
        if tag == "td":
            self._key = a.get("data-k")
            self.cells[self._key] = ""
            self.attrs[self._key] = a
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "td":
            self._key = None

    def handle_data(self, data):
        if self._key is not None:
            self.cells[self._key] += data


def parse_page(page: str) -> CellText:
    p = CellText()
    p.feed(page)
    return p


def chrome_dom(page_path: Path, fragment: str = "", extra_head_script: str = "") -> dict:
    """Open the page from disk in headless Chrome (file://) and return the self-test result."""
    target = page_path
    if extra_head_script:
        target = page_path.with_name("variant.html")
        target.write_text(page_path.read_text(encoding="utf-8").replace("<script id=\"rv-config\"", f"<script>{extra_head_script}</script><script id=\"rv-config\"", 1),
                          encoding="utf-8", newline="\n")
    prof = tempfile.mkdtemp(prefix="rv-chrome-")
    try:
        r = subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-first-run", "--no-sandbox", f"--user-data-dir={prof}",
                            "--virtual-time-budget=9000", "--dump-dom", target.as_uri() + "#" + fragment + "&selftest=1"],
                           capture_output=True, timeout=120)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    dom = r.stdout.decode("utf-8", "replace")
    m = re.search(r'id="rv-selftest">(.*?)</script>', dom, re.S)
    assert m, "no self-test result in the DOM:\n" + dom[:500]
    result = json.loads(m.group(1))
    result["_dom"] = dom
    return result


# --------------------------------------------------------------------------- 1. the original is never touched


class OriginalIntegrity(unittest.TestCase):
    """Invariant 1: the original ODS is byte-identical before and after generation."""

    def test_every_command_leaves_the_ods_byte_identical(self):
        before = (sha(ODS), ODS.stat().st_mtime_ns, rv_ods.git_blob_id(str(ODS)))
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            self.assertEqual(rv.main(["--ods", str(ODS), "--out", tmp, "build"]), 0)
            self.assertEqual(rv.main(["--ods", str(ODS), "--out", tmp, "check"]), 0)
            rv.main(["--ods", str(ODS), "status"])
        after = (sha(ODS), ODS.stat().st_mtime_ns, rv_ods.git_blob_id(str(ODS)))
        self.assertEqual(before, after)

    def test_generation_never_opens_the_ods_for_writing(self):
        real_open, writes = builtins.open, []

        def spy(file, mode="r", *a, **kw):
            if any(c in mode for c in "wax+") and Path(str(file)).resolve() == ODS.resolve():
                writes.append(mode)
            return real_open(file, mode, *a, **kw)

        with mock.patch("builtins.open", spy), mock.patch("zipfile.ZipFile.__init__", autospec=True,
                                                            side_effect=zipfile.ZipFile.__init__) as zf:
            rv.generate(ODS, ["cs"])
            modes = [c.args[2] if len(c.args) > 2 else c.kwargs.get("mode", "r") for c in zf.call_args_list]
        self.assertEqual(writes, [])
        self.assertTrue(all(m == "r" for m in modes), modes)

    def test_build_refuses_to_write_into_the_ods_folder(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            rv.main(["--ods", str(ODS), "--out", str(ODS), "build"])

    def test_a_changed_ods_during_the_run_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "w.ods"
            shutil.copyfile(ODS, copy)
            with self.assertRaises(SystemExit):
                rv.assert_unchanged(copy, "0" * 64, "0" * 40)


# --------------------------------------------------------------------------- 2. English fidelity / structure


class EnglishFidelity(unittest.TestCase):
    """The English page must carry exactly the workbook's cell texts, merges and links."""

    @classmethod
    def setUpClass(cls):
        cls.wb = rv_ods.read_workbook(str(ODS))
        cls.files, cls.report = rv.generate(ODS, ["cs"])
        cls.page = cls.files["Codelaxy-Roadmap.html"]
        cls.parsed = parse_page(cls.page)

    def test_every_cell_text_matches_the_workbook_exactly(self):
        checked = 0
        for sh in self.wb.sheets:
            for row in sh.rows:
                for c in row:
                    if c is None:
                        continue
                    key = f"{sh.name}!{c.address}"
                    self.assertIn(key, self.parsed.cells, key)
                    self.assertEqual(self.parsed.cells[key], c.text, key)
                    checked += bool(c.text)
        self.assertGreater(checked, 1400)

    def test_four_sheets_and_merged_regions(self):
        self.assertEqual([s.name for s in self.wb.sheets], ["OVERVIEW", "MICROMAP", "LONGTERMMAP", "RULES"])
        spans = [(c.colspan, c.rowspan) for s in self.wb.sheets for r in s.rows for c in r if c and (c.colspan > 1 or c.rowspan > 1)]
        self.assertGreater(len(spans), 5)
        html_spans = sum(1 for a in self.parsed.attrs.values() if "colspan" in a or "rowspan" in a)
        self.assertEqual(html_spans, len(spans))

    def test_formulas_show_their_stored_result_and_are_never_recomputed(self):
        self.assertNotIn("COUNTIF", self.page)
        self.assertNotIn("formula", self.page.lower().replace("formulas", ""))
        self.assertEqual(self.parsed.cells["OVERVIEW!B14"], "7")  # =COUNTIF(...) stored as 7 in the file

    def test_hyperlinks_are_preserved_and_validations_are_not_editable(self):
        n_links = sum(1 for s in self.wb.sheets for r in s.rows for c in r if c for p in c.paragraphs for seg in p if seg.href)
        self.assertEqual(len(self.parsed.hrefs), n_links)
        self.assertEqual(self.report["refused_links"], 0)
        for tag in ("input", "select", "textarea"):  # only the language picker exists, none inside a sheet
            sheet_part = self.page.split("<main>")[1].split("</main>")[0]
            self.assertNotIn(f"<{tag}", sheet_part)
        self.assertNotIn("contenteditable", self.page)

    def test_status_colour_semantics(self):
        want = {"DONE": "RM_St_DONE", "PARTIAL": "RM_St_PARTIAL", "PLANNED": "RM_St_PLANNED", "BLOCKED": "RM_St_BLOCKED",
                "UNKNOWN": "RM_St_UNKNOWN"}
        seen = {}
        for key, a in self.parsed.attrs.items():
            text = self.parsed.cells[key]
            if text in want and f"s-{want[text]}" in a.get("class", ""):
                seen[text] = seen.get(text, 0) + 1
        self.assertEqual(set(seen), set(want), seen)
        for name in want.values():  # and each status style really defines a colour in the page CSS
            self.assertRegex(self.page, rf"\.s-{name}\{{[^}}]*background-color:#")

    def test_reference_state_is_shown_not_hidden(self):
        cfg = json.loads(re.search(r'id="rv-config" type="application/json">(.*?)</script>', self.page, re.S).group(1))
        self.assertEqual(cfg["reference"], {"commit": "b05f2d2", "date": "2026-10-18"})
        self.assertEqual(cfg["sha256"], self.wb.sha256)
        self.assertEqual(cfg["blob"], self.wb.blob)


# --------------------------------------------------------------------------- 3-4. translations bind to their source


class TranslationBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wb = rv_ods.read_workbook(str(ODS))
        cls.src = rv.load_source("cs")

    def pack(self):
        pack, report = rv_html.build_pack(self.wb, self.src)
        return pack, report

    def test_each_translated_cell_maps_to_exactly_one_source_cell(self):
        pack, report = self.pack()
        keys = {f"{s.name}!{c.address}": c for s in self.wb.sheets for r in s.rows for c in r if c and rv_html.is_translatable_cell(c)}
        self.assertEqual(set(pack["e"]), set(keys))
        self.assertEqual(report["missing_cells"], [])
        for key, (h, text) in pack["e"].items():
            self.assertEqual(h, rv_text.text_hash(rv_text.normalize(keys[key].text)), key)
            self.assertEqual(rv_text.check_translation(rv_text.normalize(keys[key].text), text), [], key)

    def test_changed_english_text_invalidates_its_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = modified_ods(Path(tmp) / "c.ods", "<text:p>Codelaxy — Roadmap Workbook</text:p>",
                                   "<text:p>Codelaxy — Roadmap Workbook (edited)</text:p>")
            wb2 = rv_ods.read_workbook(str(changed))
            pack, report = rv_html.build_pack(wb2, self.src)
        self.assertIn("OVERVIEW!A1", report["missing_cells"])
        self.assertNotIn("OVERVIEW!A1", pack["e"])
        self.assertEqual(len(report["missing_cells"]), 1)  # only that cell loses its translation

    def test_generation_check_notices_an_ods_changed_after_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(rv.main(["--ods", str(ODS), "--out", str(out), "build"]), 0)
                changed = modified_ods(Path(tmp) / "c.ods", "<text:p>PROJECT</text:p>", "<text:p>PROJECTS</text:p>")
                self.assertEqual(rv.main(["--ods", str(changed), "--out", str(out), "check"]), 1)

    def test_a_damaged_translation_is_refused(self):
        src = json.loads(json.dumps(self.src))
        entry = next(v for v in src["entries"].values() if "OPEN-16" in v["en"])
        entry["cs"] = entry["cs"].replace("OPEN-16", "OPEN-17")
        with self.assertRaises(ValueError):
            rv_html.build_pack(self.wb, src)

    def test_hash_is_stable_across_newline_and_unicode_forms(self):
        self.assertEqual(rv_text.text_hash("a\r\nb  \n"), rv_text.text_hash("a\nb\n"))
        self.assertEqual(rv_text.text_hash("e\u0301"), rv_text.text_hash("\u00e9"))
        self.assertNotEqual(rv_text.text_hash("a b"), rv_text.text_hash("a  b"))


# --------------------------------------------------------------------------- 6. protected tokens


class ProtectedTokens(unittest.TestCase):
    def test_identifiers_statuses_files_and_hashes_are_protected_structurally(self):
        text = "P1.2-M1.4 is PARTIAL; see docs/roadmap.md, ci.yml:53, `NOT_REQUIRED`, 80a98a5, GitSnapshotBuilder and OPEN-16."
        protected = [p for prot, p in rv_text.tokenize(text) if prot]
        for token in ("P1.2-M1.4", "PARTIAL", "docs/roadmap.md", "ci.yml:53", "`NOT_REQUIRED`", "80a98a5", "GitSnapshotBuilder", "OPEN-16"):
            self.assertIn(token, protected)
        self.assertEqual("".join(p for _, p in rv_text.tokenize(text)), text)

    def test_status_words_in_a_heading_are_translatable_but_standalone_ones_are_not(self):
        self.assertTrue(rv_text.is_translatable("OPEN BLOCKERS"))
        self.assertFalse(rv_text.is_translatable("DONE"))
        self.assertFalse(rv_text.is_translatable("P1.2-M1"))
        self.assertFalse(rv_text.is_translatable("I"))

    def test_translator_receives_placeholders_not_the_protected_text(self):
        masked, tokens = rv_text.to_placeholders("Windows limit in git hash-object (F1), see OPEN-02.")
        self.assertNotIn("F1", masked)
        self.assertNotIn("OPEN-02", masked)
        self.assertEqual(tokens, ["git hash-object", "F1", "OPEN-02"])
        self.assertEqual(masked.count("\u27e6"), 3)

    def test_status_and_id_cells_are_not_offered_for_translation(self):
        page = rv.generate(ODS, ["cs"])[0]["Codelaxy-Roadmap.html"]
        parsed = parse_page(page)
        for key, a in parsed.attrs.items():
            text = parsed.cells[key].strip()
            if text in {"DONE", "PARTIAL", "PLANNED", "BLOCKED", "UNKNOWN", "OPEN", "STEP", "ITEM"} or re.fullmatch(r"P1\.\d(-[A-Z]\d+(\.\d+)?)?", text):
                self.assertNotIn("tr", a.get("class", "").split(), key)

    def test_czech_pack_keeps_every_protected_token(self):
        wb = rv_ods.read_workbook(str(ODS))
        pack, _ = rv_html.build_pack(wb, rv.load_source("cs"))
        en = {f"{s.name}!{c.address}": rv_text.normalize(c.text) for s in wb.sheets for r in s.rows for c in r if c}
        for key, (_, cs) in pack["e"].items():
            self.assertEqual(rv_text.protected_tokens(en[key]), rv_text.protected_tokens(cs), key)


# --------------------------------------------------------------------------- 7. hostile content


class HostileContent(unittest.TestCase):
    PAYLOADS = [
        ('<script>window.__pwned=1</script>', None),
        ('<img src=x onerror="window.__pwned=2">', None),
        ('"><svg/onload=window.__pwned=3>', None),
        ("click me", "javascript:window.__pwned=4"),
        ("click me 2", "JaVaScRiPt:window.__pwned=5"),
        ("click me 3", "data:text/html,<script>window.__pwned=6</script>"),
        ("click me 4", "vbscript:msgbox(1)"),
        ("click me 5", "file:///C:/Windows/win.ini"),
        ("click me 6", "../../secret.html"),
        ("fine link", "https://example.org/ok?a=1&b=2"),
        ("&lt;b&gt; & stuff", None),
    ]

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="rv-hostile-")
        cls.ods = synthetic_ods(Path(cls.tmp) / "evil.ods", [[p] for p in cls.PAYLOADS])
        files, cls.report = rv.generate(cls.ods, ["cs"])
        cls.page = files["Codelaxy-Roadmap.html"]
        cls.out = Path(cls.tmp) / "out"
        write_files(files, cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_workbook_text_is_escaped_never_html(self):
        body = self.page.split("<main>")[1].split("</main>")[0]
        self.assertIn("&lt;script&gt;window.__pwned=1&lt;/script&gt;", body)
        tags = parse_page(self.page).tags
        for forbidden in ("img", "svg", "iframe", "object", "embed"):
            self.assertNotIn(forbidden, tags)
        self.assertEqual(tags.count("script"), 2)  # our config + our viewer; nothing from the workbook

    def test_only_http_and_internal_hrefs_become_links(self):
        parsed = parse_page(self.page)
        self.assertEqual([h for h in parsed.hrefs if h != "#"], ["https://example.org/ok?a=1&b=2"])
        self.assertEqual(self.report["refused_links"], 6)  # javascript x2, data, vbscript, file, relative

    def test_nothing_executes_in_a_real_browser(self):
        if not CHROME:
            self.skipTest("Chrome not available")
        r = chrome_dom(self.out / "Codelaxy-Roadmap.html", "lang=en")
        dom = r["_dom"]
        self.assertRegex(dom, r"&lt;script&gt;window\.__pwned=1")
        self.assertEqual(len(re.findall(r"<script\b", dom)), 3)  # config, viewer, self-test result - nothing else
        self.assertNotRegex(dom, r"<img\b|<svg\b|<iframe\b")

    def test_csp_forbids_network_access_from_scripts(self):
        policy = html.unescape(self.page)
        self.assertIn("connect-src 'none'", policy)
        self.assertIn("default-src 'none'", policy)

    def test_the_browser_really_enforces_that_policy(self):
        if not CHROME:
            self.skipTest("Chrome not available")
        r = chrome_dom(self.out / "Codelaxy-Roadmap.html", "lang=en")
        self.assertTrue(r["cspBlocksNetwork"])


# --------------------------------------------------------------------------- 8. determinism


class Determinism(unittest.TestCase):
    def test_same_inputs_give_identical_output(self):
        a, _ = rv.generate(ODS, ["cs"])
        b, _ = rv.generate(ODS, ["cs"])
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2, redirect_stdout(io.StringIO()):
            rv.main(["--ods", str(ODS), "--out", t1, "build"])
            rv.main(["--ods", str(ODS), "--out", t2, "build"])
            for rel in a:
                self.assertEqual((Path(t1) / rel).read_bytes(), (Path(t2) / rel).read_bytes(), rel)

    def test_output_contains_no_timestamps_or_machine_paths(self):
        files, _ = rv.generate(ODS, ["cs"])
        blob = "\n".join(files.values())
        self.assertNotIn(str(HERE), blob)
        self.assertNotIn("AnubW", blob)
        self.assertNotRegex(blob, r"20\d\d-\d\d-\d\dT\d\d:\d\d")  # no generation timestamp


# --------------------------------------------------------------------------- 4-5. in a real browser, from disk


@unittest.skipUnless(CHROME, "Chrome not available")
class BrowserFromDisk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rv-browser-"))
        cls.files, _ = rv.generate(ODS, ["cs"])
        cls.out = cls.tmp / "out"
        write_files(cls.files, cls.out)
        cls.page = cls.out / "Codelaxy-Roadmap.html"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_default_is_english_and_nothing_is_tabbable(self):
        r = chrome_dom(self.page, "")
        self.assertEqual((r["lang"], r["mode"], r["tabindexCells"]), ("en", "none", 0))

    def test_language_in_the_url_loads_the_pack_from_disk_without_a_server(self):
        r = chrome_dom(self.page, "lang=cs")
        self.assertEqual((r["lang"], r["mode"], r["firstKind"]), ("cs", "pack", "pack"))
        self.assertEqual(r["firstText"], "Codelaxy — Sešit roadmapy")
        self.assertEqual(r["tabindexCells"], r["translatable"])

    def test_missing_pack_file_falls_back_to_english_and_says_so(self):
        broken = self.tmp / "nopack"
        write_files({"Codelaxy-Roadmap.html": self.files["Codelaxy-Roadmap.html"]}, broken)
        r = chrome_dom(broken / "Codelaxy-Roadmap.html", "lang=cs")
        self.assertEqual((r["mode"], r["tabindexCells"]), ("none", 0))
        self.assertIn("not found", re.search(r'id="status"[^>]*>(.*?)</div>', r["_dom"], re.S).group(1))
        self.assertTrue("— Roadmap Workbook" in r["_dom"])  # the English text is still on the page

    def test_changed_english_marks_the_old_translation_outdated_never_shows_it(self):
        changed = modified_ods(self.tmp / "c.ods", "<text:p>Codelaxy — Roadmap Workbook</text:p>",
                               "<text:p>Codelaxy — Roadmap Workbook (edited)</text:p>")
        files, _ = rv.generate(changed, ["cs"])
        mixed = self.tmp / "mixed"
        write_files({"Codelaxy-Roadmap.html": files["Codelaxy-Roadmap.html"], "lang/cs.js": self.files["lang/cs.js"]}, mixed)
        r = chrome_dom(mixed / "Codelaxy-Roadmap.html", "lang=cs")
        self.assertEqual(r["firstKind"], "outdated")
        self.assertIsNone(r["firstText"])

    def test_missing_translation_for_a_cell_falls_back_to_english(self):
        empty = self.tmp / "empty"
        pack = 'window.__RV_PACKS=window.__RV_PACKS||{};window.__RV_PACKS.cs={"meta":{"lang":"cs","name":"x","source_sha256":"x"},"e":{}};\n'
        write_files({"Codelaxy-Roadmap.html": self.files["Codelaxy-Roadmap.html"], "lang/cs.js": pack}, empty)
        r = chrome_dom(empty / "Codelaxy-Roadmap.html", "lang=cs")
        self.assertEqual(r["firstKind"], "missing")

    def test_unavailable_translator_never_blocks_reading(self):
        r = chrome_dom(self.page, "lang=ja", extra_head_script="try{Object.defineProperty(self,'Translator',{value:undefined})}catch(e){}")
        self.assertEqual((r["mode"], r["tabindexCells"]), ("none", 0))
        status = re.search(r'id="status"[^>]*>(.*?)</div>', r["_dom"], re.S).group(1)
        self.assertIn("no on-device translator", status)
        self.assertTrue("— Roadmap Workbook" in r["_dom"])

    def test_translation_finishing_after_a_language_switch_is_cached_under_its_own_language(self):
        fake = (
            "self.Translator={availability:function(){return Promise.resolve('available')},"
            "create:function(o){return Promise.resolve({translate:function(t){return new Promise(function(r){"
            "setTimeout(function(){r(o.targetLanguage+':'+t)},o.targetLanguage==='de'?3000:0)})}})}};"
            "window.__rvSelftestHook=function(rv){var td=document.querySelector('td.tr');var p=rv.tipContent(td);"
            "return rv.setLang('fr').then(function(){return p.catch(function(){})}).then(function(){"
            "return new Promise(function(r){setTimeout(r,4000)})})};"
        )
        r = chrome_dom(self.page, "lang=de", extra_head_script=fake)
        self.assertEqual((r["lang"], r["mode"]), ("fr", "api"))
        self.assertTrue(r["cache"], "the pending German translation never finished")
        for entry in r["cache"]:
            lang, _, rest = entry.partition("|")
            self.assertTrue(rest.split("=", 1)[1].startswith(lang + ":"), f"{lang} cache holds foreign text: {entry[:80]}")

    def test_storage_that_throws_does_not_break_the_page(self):
        blocked = "Object.defineProperty(window,'localStorage',{get:function(){throw new Error('blocked')}});"
        with_fragment = chrome_dom(self.page, "lang=cs", extra_head_script=blocked)
        self.assertEqual((with_fragment["lang"], with_fragment["mode"]), ("cs", "pack"))  # fragment needs no storage
        without = chrome_dom(self.page, "", extra_head_script=blocked)
        self.assertEqual((without["lang"], without["mode"]), ("en", "none"))  # falls back to English, still renders
        self.assertTrue("— Roadmap Workbook" in without["_dom"])

    def test_an_invalid_language_code_is_ignored_safely(self):
        r = chrome_dom(self.page, "lang=%3Cscript%3E")
        self.assertEqual((r["lang"], r["mode"]), ("en", "none"))


# --------------------------------------------------------------------------- live update while editing


class LiveUpdate(unittest.TestCase):
    """Saving the workbook (LibreOffice writes a new file and replaces the old one) refreshes the view."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rv-watch-"))
        self.ods = self.tmp / "w.ods"
        shutil.copyfile(ODS, self.ods)
        self.out, self.todo = self.tmp / "out", self.tmp / "todo.json"
        self.w = rv.Watcher(self.ods, self.out, "cs", self.todo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save_like_libreoffice(self, old: str, new: str) -> None:
        os.replace(modified_ods(self.tmp / "new.ods", old, new), self.ods)

    def test_initial_build_is_complete_and_current(self):
        self.assertIn("0 need a translation", self.w.rebuild())
        self.assertFalse(self.todo.exists())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rv.main(["--ods", str(self.ods), "--out", str(self.out), "check"]), 0)

    def test_a_save_triggers_one_rebuild_after_the_file_settles(self):
        self.w.rebuild()
        self.save_like_libreoffice("<text:p>PROJECT</text:p>", "<text:p>PROJECT (edited)</text:p>")
        self.assertIsNone(self.w.step())  # just changed: wait for the save to finish
        msg = self.w.step()
        self.assertIn("rebuilt", msg)
        self.assertIn("1 need a translation", msg)
        self.assertIn("PROJECT (edited)", (self.out / "Codelaxy-Roadmap.html").read_text(encoding="utf-8"))
        self.assertNotIn('"OVERVIEW!A2"', (self.out / "lang" / "cs.js").read_text(encoding="utf-8"))  # old translation dropped
        self.assertIn("PROJECT (edited)", json.loads(self.todo.read_text(encoding="utf-8")).values())
        self.assertIsNone(self.w.step())  # nothing changed since: nothing to do

    def test_half_written_file_is_retried_not_fatal(self):
        self.w.rebuild()
        good = self.ods.read_bytes()
        before = (self.out / "Codelaxy-Roadmap.html").read_text(encoding="utf-8")
        self.ods.write_bytes(good[:5000])  # a save in progress
        self.assertIsNone(self.w.step())
        self.assertIn("waiting", self.w.step())
        self.assertEqual((self.out / "Codelaxy-Roadmap.html").read_text(encoding="utf-8"), before)  # output untouched
        self.ods.write_bytes(good)
        self.assertIsNone(self.w.step())
        self.assertIn("rebuilt", self.w.step())

    def test_watching_never_modifies_any_workbook(self):
        before = sha(ODS)
        self.w.rebuild()
        self.save_like_libreoffice("<text:p>PROJECT</text:p>", "<text:p>PROJECT!</text:p>")
        edited = sha(self.ods)
        self.w.step()
        self.w.step()
        self.assertEqual(sha(self.ods), edited)  # the watched file is exactly what "LibreOffice" saved
        self.assertEqual(sha(ODS), before)


if __name__ == "__main__":
    unittest.main()
