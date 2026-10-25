"""Turn the workbook model into a self-contained, read-only HTML page and language packs.

Safety rules enforced here (and tested in test_roadmap_view.py):
  * every piece of cell text goes through html.escape; there is no raw HTML from the workbook;
  * a hyperlink becomes a real link only for http(s) and for #Sheet.Cell references; anything
    else (javascript:, data:, file:, relative paths) is shown as plain text;
  * formulas are never evaluated: the stored result is shown;
  * the page carries a Content-Security-Policy that forbids network access from scripts.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import rv_ods
import rv_text

HERE = Path(__file__).resolve().parent
GENERATOR = "roadmap_view 1"
SAFE_WEB = re.compile(r"^https?://[^\s<>\"']+$")
INTERNAL = re.compile(r"^#\$?([A-Za-z0-9_]+)\.\$?([A-Z]+)\$?(\d+)$")
LAST_STYLES = ("RM_St_", "RM_Sd_", "RM_Dc_", "RM_Dim", "RM_SrcI")  # conditional-format styles go after base styles

CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline' 'self' file:; "
       "img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'")


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def classify_href(href: str | None) -> tuple[str, str]:
    """('web'|'internal'|'none', normalised target)."""
    if not href:
        return "none", ""
    if SAFE_WEB.match(href):
        return "web", href
    m = INTERNAL.match(href)
    if m:
        return "internal", f"{m.group(1)}!{m.group(2)}{m.group(3)}"
    return "none", ""


def render_text(text: str, protect: bool) -> str:
    """Escaped text; when `protect`, protected tokens get <span class="np" translate="no">."""
    if not protect:
        return esc(text)
    out = []
    for prot, piece in rv_text.tokenize(text):
        out.append(f'<span class="np" translate="no">{esc(piece)}</span>' if prot else esc(piece))
    return "".join(out)


def render_cell_content(cell: rv_ods.Cell, translatable: bool) -> tuple[str, int]:
    """HTML of the paragraphs of a cell and the number of links that were refused."""
    refused = 0
    paragraphs = []
    for para in cell.paragraphs:
        parts = []
        for seg in para:
            kind, target = classify_href(seg.href)
            if seg.href and kind == "none":
                refused += 1
            if kind == "web":
                parts.append(f'<a class="np" translate="no" href="{esc(target)}" target="_blank" '
                             f'rel="noopener noreferrer">{esc(seg.text)}</a>')
            elif kind == "internal":
                parts.append(f'<a class="np" translate="no" href="#" data-goto="{esc(target)}">{esc(seg.text)}</a>')
            else:
                parts.append(render_text(seg.text, translatable))
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs), refused


def is_translatable_cell(cell: rv_ods.Cell) -> bool:
    return cell.kind == "string" and bool(cell.text) and rv_text.is_translatable(rv_text.normalize(cell.text))


def build_pack(wb: rv_ods.Workbook, src: dict) -> tuple[dict, dict]:
    """Per-cell translation entries from the language source file, plus a report."""
    entries, missing = {}, []
    for sh in wb.sheets:
        for row in sh.rows:
            for c in row:
                if c is None or not is_translatable_cell(c):
                    continue
                en = rv_text.normalize(c.text)
                h = rv_text.text_hash(en)
                item = src["entries"].get(h)
                key = f"{sh.name}!{c.address}"
                if item is None or item["en"] != en:
                    missing.append(key)
                    continue
                translated = item[src["lang"]]
                problems = rv_text.check_translation(en, translated)
                if problems:
                    raise ValueError(f"{key}: {problems}")
                entries[key] = [h, translated]
    pack = {
        "meta": {"lang": src["lang"], "name": src["name"], "source_sha256": wb.sha256, "source_blob": wb.blob,
                 "unofficial": True, "generator": GENERATOR},
        "e": dict(sorted(entries.items())),
    }
    return pack, {"translated_cells": len(entries), "missing_cells": missing}


def pack_js(pack: dict) -> str:
    """Language pack as a script (ASCII only, so no charset problem when loaded from disk)."""
    body = json.dumps(pack, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"(window.__RV_PACKS=window.__RV_PACKS||{{}}).{pack['meta']['lang']}={body};\n"


def find_reference(wb: rv_ods.Workbook) -> dict:
    """Reference commit and inventory date as written on the OVERVIEW sheet (no guessing)."""
    ref = {"commit": "", "date": ""}
    for sh in wb.sheets:
        if sh.name != "OVERVIEW":
            continue
        for row in sh.rows:
            cells = [c for c in row if c is not None]
            if len(cells) >= 2 and cells[0].text == "Reference commit":
                m = re.search(r"\b[0-9a-f]{7,40}\b", cells[1].text)
                ref["commit"] = m.group(0) if m else ""
            if len(cells) >= 2 and cells[0].text == "Inventory date":
                m = re.search(r"\d{4}-\d{2}-\d{2}", cells[1].text)
                ref["date"] = m.group(0) if m else ""
    return ref


def render_html(wb: rv_ods.Workbook, pack_files: list[dict], ods_name: str) -> tuple[str, dict]:
    used_styles: dict[str, str] = {}
    refused = 0
    n_tr = 0
    sheets_html, tabs = [], []
    for sh in wb.sheets:
        tabs.append(sh.name)
        cols = "".join(f'<col style="width:{w}cm">' for w in sh.widths_cm)
        total = round(sum(sh.widths_cm), 2)
        rows_html = []
        for r, row in enumerate(sh.rows):
            h = sh.row_heights_cm[r] if r < len(sh.row_heights_cm) else None
            cells_html = []
            for c in row:
                if c is None:
                    continue
                classes = []
                if c.style:
                    classes.append(f"s-{c.style}")
                    used_styles[c.style] = wb.style_css.get(c.style, "")
                if c.status_class:
                    classes.append(f"s-{c.status_class}")
                    used_styles[c.status_class] = wb.style_css.get(c.status_class, "")
                tr = is_translatable_cell(c)
                attrs = f'data-k="{esc(sh.name)}!{c.address}"'
                if tr:
                    n_tr += 1
                    classes.append("tr")
                    attrs += f' data-h="{rv_text.text_hash(rv_text.normalize(c.text))}"'
                if c.colspan > 1:
                    attrs += f' colspan="{c.colspan}"'
                if c.rowspan > 1:
                    attrs += f' rowspan="{c.rowspan}"'
                content, bad = render_cell_content(c, tr)
                refused += bad
                cells_html.append(f'<td class="{" ".join(classes)}" {attrs}>{content}</td>')
            style = f' style="height:{h}cm"' if h else ""
            rows_html.append(f"<tr{style}>{''.join(cells_html)}</tr>")
        sheets_html.append(
            f'<section class="sheet" id="sheet-{esc(sh.name)}" role="tabpanel" aria-label="{esc(sh.name)}" hidden>'
            f'<div class="scroll"><table style="width:{total}cm"><colgroup>{cols}</colgroup>'
            f'<tbody>{"".join(rows_html)}</tbody></table></div></section>'
        )

    base = sorted((n for n in used_styles if not n.startswith(LAST_STYLES)))
    late = sorted((n for n in used_styles if n.startswith(LAST_STYLES)))
    style_css = "\n".join(f".s-{n}{{{used_styles[n]}}}" for n in base + late if used_styles[n])
    css = (HERE / "viewer.css").read_text(encoding="utf-8")
    js = (HERE / "viewer.js").read_text(encoding="utf-8")
    config = {
        "file": ods_name, "sha256": wb.sha256, "blob": wb.blob, "reference": find_reference(wb),
        "sheets": tabs, "packs": pack_files, "generator": GENERATOR,
        "counts": {"translatable_cells": n_tr, "refused_links": refused, "notes_omitted": wb.n_notes,
                   "validations_ignored": wb.n_validations},
    }
    config_json = json.dumps(config, ensure_ascii=True, sort_keys=True).replace("</", "<\\/")
    tab_html = "".join(f'<button type="button" role="tab" class="tab" data-sheet="{esc(n)}">{esc(n)}</button>' for n in tabs)
    page = f"""<!doctype html>
<html lang="en" data-lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{esc(CSP)}">
<meta name="rv-source-sha256" content="{wb.sha256}">
<meta name="rv-source-blob" content="{wb.blob}">
<meta name="rv-generator" content="{GENERATOR}">
<title>Codelaxy Roadmap - read-only view</title>
<style>
{css}
{style_css}
</style>
</head>
<body>
<header class="top">
<div class="titles"><h1 id="t-title"></h1><p id="t-source" class="muted"></p></div>
<div class="langbox">
<label for="lang" id="t-language"></label>
<select id="lang"></select>
<span id="other-box" hidden><input id="other-code" list="codes" size="8" autocomplete="off" spellcheck="false" aria-label="language code"><datalist id="codes"></datalist><button type="button" id="other-apply"></button></span>
</div>
</header>
<div class="banner" role="note"><strong id="t-ref"></strong> <span id="t-hist"></span> <span id="t-unofficial"></span></div>
<div id="status" class="status" role="status" aria-live="polite"></div>
<nav class="tabs" role="tablist" aria-label="Sheets">{tab_html}</nav>
<main>
{"".join(sheets_html)}
</main>
<div id="tip" role="tooltip" hidden></div>
<script id="rv-config" type="application/json">{config_json}</script>
<script>
{js}
</script>
</body>
</html>
"""
    return page, config
