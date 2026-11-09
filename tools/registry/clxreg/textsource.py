"""IMP2-04 - literal search in source text: labels, quotes and ranges.

Nothing here interprets meaning. A label is *evidenced* only by a literal occurrence with non-word characters (or the text edge) on both sides;
a quote only by an exact substring (no case folding, no whitespace or line-ending normalisation, dashes are not interchangeable).
A label between the ends of a range is never a literal occurrence: it can be at most "implied by range" (see parse_range / label_between).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class SourceTextError(ValueError):
    pass


@dataclass(frozen=True)
class Occurrence:
    offset: int          # character offset in the decoded text (a BOM, if present, counts as one character)
    line: int            # 1-based; lines end at LF
    column: int          # 1-based, in characters


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SourceTextError(f"source is not valid UTF-8: {e}") from e


def _word(c: str) -> bool:
    return c.isalnum() or c == "_"


def _occurrence(text: str, offset: int) -> Occurrence:
    line = text.count("\n", 0, offset) + 1
    return Occurrence(offset, line, offset - (text.rfind("\n", 0, offset) + 1) + 1)


def find_label(text: str, label: str) -> list:
    if not label or re.search(r"\s", label):
        raise ValueError(f"a label must be non-empty and contain no whitespace: {label!r}")
    out, start = [], 0
    while True:
        i = text.find(label, start)
        if i < 0:
            return out
        before = text[i - 1] if i > 0 else ""
        after = text[i + len(label)] if i + len(label) < len(text) else ""
        if not (before and _word(before)) and not (after and _word(after)):
            out.append(_occurrence(text, i))
        start = i + 1


def find_quote(text: str, quote: str) -> list:
    if not quote:
        raise ValueError("an empty quote proves nothing")
    out, start = [], 0
    while True:
        i = text.find(quote, start)
        if i < 0:
            return out
        out.append(_occurrence(text, i))
        start = i + 1


def contains_quote(text: str, quote: str) -> bool:
    return bool(find_quote(text, quote))


_NUM = r"(0|[1-9][0-9]*)"
_RANGE = re.compile(r"([A-Za-z]+)" + _NUM + r" ?[–—-] ?([A-Za-z]+)" + _NUM)
_LABEL = re.compile(r"([A-Za-z]+)" + _NUM)


def parse_range(quote: str):
    """('RT', 1, 3) for 'RT1–RT3' (en dash, em dash or hyphen-minus, optional single spaces); None for anything else."""
    m = _RANGE.fullmatch(quote)
    if not m or m.group(1) != m.group(3):
        return None
    lo, hi = int(m.group(2)), int(m.group(4))
    return (m.group(1), lo, hi) if lo < hi else None


def label_between(label: str, range_quote: str) -> bool:
    """True only if `label` has the range's prefix and a number strictly between its ends (the ends themselves are literal labels)."""
    r = parse_range(range_quote)
    m = _LABEL.fullmatch(label)
    return bool(r and m and m.group(1) == r[0] and r[1] < int(m.group(2)) < r[2])


def is_word(c: str) -> bool:
    """The boundary rule of find_label, for callers that scan with their own patterns."""
    return _word(c)
