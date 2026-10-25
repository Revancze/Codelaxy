"""Read-only reader for the Codelaxy roadmap workbook (.ods) -> a plain data model.

Only the pieces the viewer needs: sheets, cells (displayed text, links, notes, spans), the
stored result of formulas (never recomputed), column widths, row heights, cell styles as CSS
and the status colours that LibreOffice applies through conditional formats.

The file is opened with mode "rb" only. Nothing here can write to it.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "calcext": "urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


# --------------------------------------------------------------------------- identity


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:  # read-only
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_id(path: str) -> str:
    """The id git would give this file (sha1 of 'blob <size>\\0' + bytes), computed without git."""
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# --------------------------------------------------------------------------- model


@dataclass
class Segment:
    text: str = ""
    href: str | None = None  # raw xlink:href of a hyperlink segment


@dataclass
class Cell:
    row: int
    col: int
    style: str = ""
    css: str = ""
    kind: str = "empty"  # empty | string | float | percentage | date | boolean | other
    paragraphs: list[list[Segment]] = field(default_factory=list)
    has_formula: bool = False
    colspan: int = 1
    rowspan: int = 1
    note: list[str] = field(default_factory=list)  # office:annotation paragraphs
    status_class: str = ""  # RM_St_* style applied by a conditional format

    @property
    def text(self) -> str:
        """The displayed text: paragraphs joined by newlines."""
        return "\n".join("".join(s.text for s in p) for p in self.paragraphs)

    @property
    def address(self) -> str:
        return f"{col_letter(self.col)}{self.row + 1}"


@dataclass
class Sheet:
    name: str
    widths_cm: list[float]
    rows: list[list[Cell | None]]  # None marks a cell covered by a merge
    row_heights_cm: list[float | None]
    n_cols: int
    n_rows: int
    tab_color: str = ""


@dataclass
class Workbook:
    sheets: list[Sheet]
    sha256: str
    blob: str
    n_validations: int
    n_conditional: int
    style_css: dict[str, str] = field(default_factory=dict)
    n_notes: int = 0


def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


# --------------------------------------------------------------------------- styles -> css


def _length(v: str) -> str:
    return v  # cm / mm / pt / in are all valid CSS lengths


def _border(v: str) -> str:
    if v == "none":
        return "none"
    m = re.match(r"([\d.]+)(pt|cm|mm)\s+(\w+)\s+(#[0-9a-fA-F]{6})", v)
    if not m:
        return "1px solid #888"
    width = "1px" if float(m.group(1)) < 0.9 and m.group(2) == "pt" else f"{m.group(1)}{m.group(2)}"
    return f"{width} {m.group(3)} {m.group(4)}"


def style_to_css(props: dict[str, str]) -> str:
    css = []
    cell = props
    mapping = {
        "fo:background-color": "background-color", "fo:color": "color", "fo:font-weight": "font-weight",
        "fo:font-style": "font-style", "fo:font-size": "font-size",
    }
    for key, prop in mapping.items():
        v = cell.get(key)
        if v and v != "transparent":
            css.append(f"{prop}:{_length(v)}")
    if cell.get("style:font-name"):
        css.append(f"font-family:'{cell['style:font-name']}',Calibri,'Segoe UI',system-ui,sans-serif")
    if cell.get("style:text-underline-style") not in (None, "none"):
        css.append("text-decoration:underline")
    for side in ("top", "bottom", "left", "right"):
        v = cell.get(f"fo:border-{side}") or cell.get("fo:border")
        if v:
            css.append(f"border-{side}:{_border(v)}")
    ta = cell.get("fo:text-align")
    if ta:
        css.append("text-align:" + {"start": "left", "end": "right"}.get(ta, ta))
    va = cell.get("style:vertical-align")
    if va:
        css.append("vertical-align:" + {"automatic": "bottom"}.get(va, va))
    if cell.get("fo:wrap-option") == "wrap":
        css.append("white-space:pre-wrap;overflow-wrap:anywhere")
    else:
        css.append("white-space:pre")
    for pad in ("fo:padding", "fo:padding-left", "fo:padding-right", "fo:padding-top", "fo:padding-bottom"):
        if cell.get(pad):
            css.append(f"{pad[3:]}:{_length(cell[pad])}")
    return ";".join(css)


def collect_styles(roots: list[ET.Element]) -> dict[str, dict[str, str]]:
    """Merge style:style elements of family table-cell, following parent-style-name."""
    raw: dict[str, tuple[str | None, dict[str, str]]] = {}
    for root in roots:
        for st in root.iter(q("style", "style")):
            if st.get(q("style", "family")) != "table-cell":
                continue
            props: dict[str, str] = {}
            for child in st:
                if child.tag in (q("style", "table-cell-properties"), q("style", "text-properties"),
                                 q("style", "paragraph-properties")):
                    for k, v in child.attrib.items():
                        ns, _, name = k[1:].partition("}")
                        prefix = next((p for p, u in NS.items() if u == ns), None)
                        if prefix:
                            props[f"{prefix}:{name}"] = v
            raw[st.get(q("style", "name"))] = (st.get(q("style", "parent-style-name")), props)
    resolved: dict[str, dict[str, str]] = {}

    def resolve(name: str, depth: int = 0) -> dict[str, str]:
        if name in resolved:
            return resolved[name]
        parent, props = raw.get(name, (None, {}))
        base = resolve(parent, depth + 1) if parent and depth < 10 and parent in raw else {}
        resolved[name] = {**base, **props}
        return resolved[name]

    for name in raw:
        resolve(name)
    return resolved


# --------------------------------------------------------------------------- cell text


def _segments(p: ET.Element) -> list[Segment]:
    segs: list[Segment] = []

    def add(text: str, href: str | None = None) -> None:
        if text:
            if segs and segs[-1].href == href:
                segs[-1].text += text
            else:
                segs.append(Segment(text, href))

    def walk(el: ET.Element, href: str | None) -> None:
        add(el.text or "", href)
        for child in el:
            if child.tag == q("text", "s"):
                add(" " * int(child.get(q("text", "c"), "1")), href)
            elif child.tag == q("text", "tab"):
                add("\t", href)
            elif child.tag == q("text", "line-break"):
                add("\n", href)
            elif child.tag == q("text", "a"):
                walk(child, child.get(q("xlink", "href")))
            else:
                walk(child, href)
            add(child.tail or "", href)

    walk(p, None)
    return segs


def _parse_ref(ref: str) -> tuple[str, int, int]:
    m = re.match(r"\$?([^.$]+)\.\$?([A-Z]+)\$?(\d+)", ref.replace("'", ""))
    if not m:
        raise ValueError(ref)
    return m.group(1), col_index(m.group(2)), int(m.group(3)) - 1


def _range_bounds(rng: str) -> tuple[str, int, int, int, int]:
    a, _, b = rng.partition(":")
    sheet, c1, r1 = _parse_ref(a)
    _, c2, r2 = _parse_ref(b or a)
    return sheet, c1, r1, c2, r2


# --------------------------------------------------------------------------- reader


def read_workbook(path: str) -> Workbook:
    with zipfile.ZipFile(path, "r") as z:  # read-only
        content = ET.fromstring(z.read("content.xml"))
        styles_xml = ET.fromstring(z.read("styles.xml"))
    styles = collect_styles([styles_xml, content])
    css_cache = {name: style_to_css(props) for name, props in styles.items()}

    # column / row styles (automatic styles in content.xml)
    col_w: dict[str, float] = {}
    row_h: dict[str, float] = {}
    tab_colors: dict[str, str] = {}
    for st in content.iter(q("style", "style")):
        fam, name = st.get(q("style", "family")), st.get(q("style", "name"))
        for child in st:
            if fam == "table-column" and child.tag == q("style", "table-column-properties"):
                w = child.get(q("style", "column-width"), "")
                if w.endswith("cm"):
                    col_w[name] = float(w[:-2])
            if fam == "table-row" and child.tag == q("style", "table-row-properties"):
                h = child.get(q("style", "row-height"), "")
                if h.endswith("cm"):
                    row_h[name] = float(h[:-2])
            if fam == "table" and child.tag == q("style", "table-properties"):
                tc = child.get("{urn:org:documentfoundation:names:experimental:calc:xmlns:tableooo:1.0}tab-color") or \
                     next((v for k, v in child.attrib.items() if k.endswith("tab-color")), "")
                tab_colors[name] = tc

    # conditional formats: (sheet, c1, r1, c2, r2, [(value, style)])
    conds: list[tuple[str, int, int, int, int, list[tuple[str, str]]]] = []
    for cf in content.iter(q("calcext", "conditional-format")):
        sheet, c1, r1, c2, r2 = _range_bounds(cf.get(q("calcext", "target-range-address"), ""))
        rules = []
        for cond in cf.iter(q("calcext", "condition")):
            m = re.match(r'^="(.*)"$', cond.get(q("calcext", "value"), ""))
            if m:
                rules.append((m.group(1), cond.get(q("calcext", "apply-style-name"), "")))
        conds.append((sheet, c1, r1, c2, r2, rules))

    sheets: list[Sheet] = []
    spreadsheet = content.find(f".//{q('office', 'spreadsheet')}")
    for tab in spreadsheet.findall(q("table", "table")):
        name = tab.get(q("table", "name"))
        pr = tab.get(q("table", "print-ranges"))
        if pr:
            _, _, _, max_c, max_r = _range_bounds(pr)
            n_cols, n_rows = max_c + 1, max_r + 1
        else:
            n_cols, n_rows = 0, 0
        widths: list[float] = []
        for col in tab.findall(q("table", "table-column")):
            rep = int(col.get(q("table", "number-columns-repeated"), "1"))
            widths += [col_w.get(col.get(q("table", "style-name"), ""), 2.5)] * min(rep, 64)
        rows: list[list[Cell | None]] = []
        heights: list[float | None] = []
        r = 0
        for row in tab.findall(q("table", "table-row")):
            rrep = int(row.get(q("table", "number-rows-repeated"), "1"))
            if n_rows and r >= n_rows:
                break
            cells: list[Cell | None] = []
            c = 0
            for el in row:
                if el.tag not in (q("table", "table-cell"), q("table", "covered-table-cell")):
                    continue
                crep = int(el.get(q("table", "number-columns-repeated"), "1"))
                for _ in range(min(crep, max(0, (n_cols or 64) - c))):
                    if el.tag == q("table", "covered-table-cell"):
                        cells.append(None)
                    else:
                        cells.append(_read_cell(el, r, c, styles, css_cache))
                    c += 1
            for _ in range(min(rrep, 200 if not n_rows else n_rows - r)):
                rows.append([None if x is None else Cell(**{**x.__dict__, "row": r}) for x in cells]
                            if rrep > 1 else cells)
                heights.append(row_h.get(row.get(q("table", "style-name"), "")))
                r += 1
        if not n_rows:
            n_rows = len(rows)
        if not n_cols:
            n_cols = max((len(x) for x in rows), default=0)
        sheets.append(Sheet(name, widths[:n_cols] + [2.5] * max(0, n_cols - len(widths)), rows[:n_rows],
                            heights[:n_rows], n_cols, n_rows, tab_colors.get(tab.get(q("table", "style-name"), ""), "")))

    # apply conditional formats on the stored text of each cell
    by_name = {s.name: s for s in sheets}
    for sheet_name, c1, r1, c2, r2, rules in conds:
        sh = by_name.get(sheet_name)
        if not sh:
            continue
        for rr in range(r1, min(r2, len(sh.rows) - 1) + 1):
            for cc in range(c1, min(c2, len(sh.rows[rr]) - 1) + 1):
                cell = sh.rows[rr][cc]
                if cell is None:
                    continue
                for value, style in rules:
                    if cell.text == value:
                        cell.status_class = style
                        break

    n_val = len(list(content.iter(q("table", "content-validation"))))
    n_notes = len(list(content.iter(q("office", "annotation"))))
    return Workbook(sheets, sha256_file(path), git_blob_id(path), n_val, len(conds), css_cache, n_notes)


def _read_cell(el: ET.Element, r: int, c: int, styles: dict, css_cache: dict) -> Cell:
    style = el.get(q("table", "style-name"), "")
    cell = Cell(
        row=r, col=c, style=style, css=css_cache.get(style, ""),
        colspan=int(el.get(q("table", "number-columns-spanned"), "1")),
        rowspan=int(el.get(q("table", "number-rows-spanned"), "1")),
        has_formula=bool(el.get(q("table", "formula"))),
    )
    vt = el.get(q("office", "value-type"))
    cell.kind = {"string": "string", "float": "float", "percentage": "percentage", "date": "date",
                 "boolean": "boolean"}.get(vt, "other" if vt else "empty")
    for p in el.findall(q("text", "p")):
        cell.paragraphs.append(_segments(p))
    ann = el.find(q("office", "annotation"))
    if ann is not None:
        cell.note = ["".join(s.text for s in _segments(p)) for p in ann.findall(q("text", "p"))]
    return cell
