"""IMP2-01 - canonical JSON form, strict reader and digests.

Form of a record file: UTF-8 without BOM, LF, 2-space indent, keys sorted by Unicode CODE POINT, one trailing LF, non-ASCII written raw.
Digest: SHA-256 of the compact form (`,` and `:` without spaces) of the normative content, UTF-8.
Only null, booleans, integers, strings, arrays and objects with string keys exist: floats are rejected (no cross-language ambiguity).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class CanonError(ValueError):
    pass


def _check(o, where="$"):
    if o is None or isinstance(o, bool):
        return
    if isinstance(o, int):
        return
    if isinstance(o, str):
        try:
            o.encode("utf-8")
        except UnicodeEncodeError as e:
            raise CanonError(f"{where}: string is not valid Unicode (lone surrogate)") from e
        return
    if isinstance(o, list):
        for i, x in enumerate(o):
            _check(x, f"{where}[{i}]")
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if not isinstance(k, str):
                raise CanonError(f"{where}: object key {k!r} is not a string")
            _check(k, f"{where}.<key>")
            _check(v, f"{where}.{k}")
        return
    raise CanonError(f"{where}: unsupported type {type(o).__name__}")


def dumps(obj) -> str:
    _check(obj)
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def dumps_compact(obj) -> str:
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj) -> str:
    return hashlib.sha256(dumps_compact(obj).encode("utf-8")).hexdigest()


def _no_duplicates(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise CanonError(f"duplicate key {k!r}")
        d[k] = v
    return d


def _reject(token):
    raise CanonError(f"number {token!r} is not allowed (integers only)")


def loads(text: str):
    if text.startswith("﻿"):
        raise CanonError("byte order mark")
    try:
        obj = json.loads(text, object_pairs_hook=_no_duplicates, parse_float=_reject, parse_constant=_reject)
    except CanonError:
        raise
    except ValueError as e:
        raise CanonError(f"invalid JSON: {e}") from e
    _check(obj)
    return obj


def is_canonical(text: str) -> bool:
    try:
        return dumps(loads(text)) == text
    except CanonError:
        return False


def write_record(path, obj, overwrite: bool = False) -> None:
    text = dumps(obj)
    with open(Path(path), "w" if overwrite else "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


_NORMATIVE = {
    "REQ": ("statement", "acceptance", "applies_to"),
    "SCN": ("procedure", "expected", "platforms_required"),
}


def normative_digest(rec: dict) -> str:
    t = rec.get("type")
    if t not in _NORMATIVE:
        raise CanonError(f"no normative content defined for type {t!r}")
    try:
        content = {k: rec[k] for k in _NORMATIVE[t]}
    except KeyError as e:
        raise CanonError(f"{t} record lacks normative field {e.args[0]!r}") from e
    if t == "SCN" and "mutant" in rec:
        content["mutant"] = rec["mutant"]
    return digest(content)
