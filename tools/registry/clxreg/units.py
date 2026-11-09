"""IMP2-05 - units of a source: the addressable pieces of text a ledger scans (text lines, ODS paragraphs).

Lossless: lines are split at LF only and keep CR, BOM and every other character; ODS paragraphs keep spaces, tabs and line breaks.
Explicit about limits: a source that cannot be read completely (not UTF-8, unknown suffix, ODS content this reader does not extract) raises
UnsupportedSource, which the ledger records as UNSUPPORTED - it is never skipped, never read partially.
ODS: units are the paragraphs of cells (`SHEET!R<row>C<col>/p<k>`) and of cell annotations (`.../n<j>p<k>`); empty paragraphs are not units;
validation messages and metadata outside cells are not extracted (annotation author and date are ignored).
"""
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath

TEXT_SUFFIXES = (".md", ".txt", ".json", ".py", ".sdoc", ".cs", ".yml", ".yaml", ".diff")
MAX_REPEAT = 10000

_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_TX = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_OF = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_DC = "{http://purl.org/dc/elements/1.1/}"


class UnsupportedSource(ValueError):
    pass


@dataclass(frozen=True)
class Unit:
    id: str
    text: str
    line: int | None = None      # 1-based line of a text unit; None for ODS


def read_units(suffix: str, data: bytes) -> list:
    s = suffix.lower()
    if s in TEXT_SUFFIXES:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise UnsupportedSource(f"not valid UTF-8: {e}") from e
        return [Unit(f"L{n}", line, n) for n, line in enumerate(text.split("\n"), 1)]
    if s == ".ods":
        return _ods(data)
    raise UnsupportedSource(f"unsupported source type {suffix!r}")


def suffix_of(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).suffix


def find_unit(us, unit_id):
    return next((u for u in us if u.id == unit_id), None)


def _para(el) -> str:
    out = [el.text or ""]
    for ch in el:
        if ch.tag == _TX + "s":
            out.append(" " * int(ch.get(_TX + "c", "1")))
        elif ch.tag == _TX + "tab":
            out.append("\t")
        elif ch.tag == _TX + "line-break":
            out.append("\n")
        elif ch.tag in (_TX + "span", _TX + "a"):
            out.append(_para(ch))
        else:
            raise UnsupportedSource(f"ODS paragraph contains an element this reader does not extract: {ch.tag}")
        out.append(ch.tail or "")
    return "".join(out)


def _cell_units(cell):
    """[(suffix, text)] for the paragraphs of one cell, in document order; anything else inside a cell is unsupported."""
    out, k, notes = [], 0, 0
    for ch in cell:
        if ch.tag in (_TX + "p", _TX + "h"):
            k += 1
            t = _para(ch)
            if t:
                out.append((f"/p{k}", t))
        elif ch.tag == _OF + "annotation":
            notes += 1
            j = 0
            for sub in ch:
                if sub.tag in (_DC + "creator", _DC + "date"):
                    continue
                if sub.tag not in (_TX + "p", _TX + "h"):
                    raise UnsupportedSource(f"ODS annotation contains an element this reader does not extract: {sub.tag}")
                j += 1
                t = _para(sub)
                if t:
                    out.append((f"/n{notes}p{j}", t))
        else:
            raise UnsupportedSource(f"ODS cell contains an element this reader does not extract: {ch.tag}")
    return out


def _repeat(el, attr) -> int:
    try:
        n = int(el.get(_T + attr, "1"))
    except ValueError as e:
        raise UnsupportedSource(f"bad {attr}") from e
    if n < 1:
        raise UnsupportedSource(f"bad {attr}")
    return n


def _ods(data: bytes) -> list:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("content.xml")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as e:
        raise UnsupportedSource(f"not a readable ODS: {e}") from e
    body = root.find(_OF + "body")
    sheet_root = body.find(_OF + "spreadsheet") if body is not None else None
    if sheet_root is None:
        raise UnsupportedSource("ODS without a spreadsheet body")
    out = []
    for table in sheet_root.findall(_T + "table"):
        name = table.get(_T + "name", "")
        rn = 1
        for r in table.iter(_T + "table-row"):
            row_rep = _repeat(r, "number-rows-repeated")
            cn = 1
            for c in r:
                if c.tag not in (_T + "table-cell", _T + "covered-table-cell"):
                    continue
                col_rep = _repeat(c, "number-columns-repeated")
                us = _cell_units(c) if c.tag == _T + "table-cell" else []
                if us:
                    if row_rep * col_rep > MAX_REPEAT:
                        raise UnsupportedSource(f"a non-empty cell is repeated {row_rep * col_rep} times in {name}")
                    for rr in range(row_rep):
                        for cc in range(col_rep):
                            for suffix, text in us:
                                out.append(Unit(f"{name}!R{rn + rr}C{cn + cc}{suffix}", text))
                cn += col_rep
            rn += row_rep
    return out
