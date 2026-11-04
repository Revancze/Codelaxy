"""IMP2-06 - finding labels in text: namespace patterns (data, from the namespace catalog), ranges, a second pass for label-like tokens, ambiguity.

The scanner interprets nothing. A string matched by the patterns of two namespaces is ONE match carrying both namespaces (never merged into one,
never resolved). A range is one RANGE match; its members are never created. A match inside a longer one is kept *inside* it (`contained`), not
dropped. Label-like tokens that no namespace claims are reported (UNCLASSIFIED), also next to hyphens - nothing is skipped because of its neighbours.
Every match needs word boundaries on both sides (the rule of textsource.find_label).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import sources, textsource
from .findings import data_error

AMBIGUITY_SCHEMA = "clx.ambiguity/1"
LABEL, RANGE, UNCLASSIFIED = "LABEL", "RANGE", "UNCLASSIFIED"
_RANK = {LABEL: 0, UNCLASSIFIED: 1, RANGE: 2}

_GENERIC = re.compile(r"[A-Z][A-Z0-9]{0,5}-?[0-9]+[a-z]?")
_RANGE = re.compile(r"([A-Z]{1,4})([0-9]+)([ab]?)[ \t]*(?:[–—…]|\.\.|-(?=\1))[ \t]*(\1)?([0-9]+)([ab]?)")


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    text: str
    cls: str                                  # LABEL, RANGE or UNCLASSIFIED
    namespaces: tuple = ()                    # LABEL: every namespace whose pattern matched exactly this span
    ends: tuple | None = None                 # RANGE: (first literal, last literal)
    contained: tuple = ()                     # shorter LABEL / UNCLASSIFIED matches lying inside this one


def compile_namespaces(cat) -> list:
    if not (isinstance(cat, dict) and isinstance(cat.get("namespaces"), list)):
        raise ValueError("the namespace catalog must be an object with a 'namespaces' list")
    out = []
    for n in cat["namespaces"]:
        if not (isinstance(n, dict) and isinstance(n.get("key"), str) and isinstance(n.get("label_pattern"), str)):
            raise ValueError("every namespace needs a string key and label_pattern")
        try:
            rx = re.compile(n["label_pattern"])
        except re.error as e:
            raise ValueError(f"namespace {n['key']}: invalid label_pattern: {e}") from e
        if rx.fullmatch("") is not None:
            raise ValueError(f"namespace {n['key']}: label_pattern matches the empty string")
        out.append((n["key"], rx))
    return out


def boundary_matches(rx, text):
    """Non-overlapping boundary-valid matches; a match that fails the boundary test does not hide one that starts inside it."""
    out, pos = [], 0
    while True:
        m = rx.search(text, pos)
        if not m:
            return out
        s, e = m.span()
        if not (s > 0 and textsource.is_word(text[s - 1])) and not (e < len(text) and textsource.is_word(text[e])):
            out.append(m)
            pos = e
        else:
            pos = s + 1


def scan_text(text: str, compiled) -> list:
    labels = {}
    for key, rx in compiled:
        for m in boundary_matches(rx, text):
            labels.setdefault(m.span(), set()).add(key)
    items = [(s, e, LABEL, tuple(sorted(ns))) for (s, e), ns in labels.items()]
    for m in boundary_matches(_GENERIC, text):
        if m.span() not in labels:
            items.append((m.start(), m.end(), UNCLASSIFIED, ()))
    items.sort(key=lambda i: (i[0], -(i[1] - i[0]), _RANK[i[2]]))

    def encloses(o, i):
        return o[0] <= i[0] and i[1] <= o[1] and (o[1] - o[0]) > (i[1] - i[0])

    maximal = [i for i in items if not any(encloses(o, i) for o in items)]
    held = {m: [] for m in maximal}
    for i in items:
        if i in held:
            continue
        outer = next(o for o in maximal if encloses(o, i))
        held[outer].append(i)

    def mk(i, contained=()):
        return Match(i[0], i[1], text[i[0]:i[1]], i[2], i[3], None, tuple(contained))

    out = [mk(o, [mk(c) for c in sorted(held[o], key=lambda c: (c[0], c[1], _RANK[c[2]]))]) for o in maximal]
    for m in boundary_matches(_RANGE, text):
        first = m.group(1) + m.group(2) + m.group(3)
        last = (m.group(4) or "") + m.group(5) + m.group(6)
        out.append(Match(m.start(), m.end(), m.group(0), RANGE, (), (first, last)))
    out.sort(key=lambda m: (m.start, m.end, _RANK[m.cls]))
    return out


# --- ambiguity rules (data; who decides is the owner, TD-9) -------------------------------------------------------------------------
def validate_ambiguity(obj, ns_obj) -> list:
    out = []

    def err(code, rec, msg):
        out.append(data_error(code, rec, msg))

    if not isinstance(obj, dict):
        return [data_error("DE-02", "ambiguity", "the ambiguity rules must be a JSON object")]
    for k in sorted(set(obj) - {"schema", "rules"}):
        err("DE-02", "ambiguity", f"unknown top-level field {k!r}")
    if obj.get("schema") != AMBIGUITY_SCHEMA:
        err("DE-02", "ambiguity", f"schema must be {AMBIGUITY_SCHEMA!r}, found {obj.get('schema')!r}")
    rules = obj.get("rules")
    if not isinstance(rules, list):
        err("DE-02", "ambiguity", "'rules' must be a list")
        return sorted(out, key=lambda f: (f.record, f.code, f.message))
    patterns = {}
    for n in ns_obj.get("namespaces", []) if isinstance(ns_obj, dict) else []:
        if isinstance(n, dict) and isinstance(n.get("key"), str) and isinstance(n.get("label_pattern"), str):
            try:
                patterns[n["key"]] = re.compile(n["label_pattern"])
            except re.error:
                pass
    seen = {}
    for i, r in enumerate(rules):
        rec = f"ambiguity[{i}]"
        if not isinstance(r, dict):
            err("DE-02", rec, "a rule must be a JSON object")
            continue
        ns, value = r.get("namespace"), r.get("value")
        if isinstance(ns, str) and ns:
            rec = f"ambiguity:{ns}" + (f":{value}" if isinstance(value, str) else "")
        for f in sorted({"namespace", "meanings", "basis"} - set(r)):
            err("DE-02", rec, f"missing field {f!r}")
        for f in sorted(set(r) - {"namespace", "meanings", "basis", "value"}):
            err("DE-02", rec, f"unknown field {f!r}")
        mean = r.get("meanings")
        if "meanings" in r and not (isinstance(mean, list) and len(mean) >= 2 and all(isinstance(x, str) and x for x in mean) and len(set(mean)) == len(mean)):
            err("DE-02", rec, "meanings must be a list of at least two distinct non-empty strings")
        if "basis" in r and not (isinstance(r["basis"], str) and r["basis"]):
            err("DE-02", rec, "basis must be a non-empty string (where the several meanings are documented)")
        if "value" in r and not (isinstance(value, str) and value):
            err("DE-02", rec, "value must be a non-empty string")
        if not isinstance(ns, str):
            if "namespace" in r:
                err("DE-02", rec, "namespace must be a string")
            continue
        if ns not in patterns:
            err("DE-03", rec, f"namespace {ns!r} is not in the namespace catalog")
        elif isinstance(value, str) and value and not patterns[ns].fullmatch(value):
            err("DE-05", rec, f"value {value!r} does not match the pattern of the namespace {ns!r}")
        key = (ns, value if isinstance(value, str) else None)
        seen[key] = seen.get(key, 0) + 1
    for key, n in sorted(seen.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        if n > 1:
            err("DE-01", f"ambiguity:{key[0]}" + (f":{key[1]}" if key[1] else ""), f"the rule is given {n} times")
    return sorted(out, key=lambda f: (f.record, f.code, f.message))


def ambiguity_meanings(obj, namespace, value):
    """The meanings the rules give to this label (a rule for the exact value wins over one for the whole namespace), or None."""
    if not (isinstance(obj, dict) and isinstance(obj.get("rules"), list)):
        return None
    best = None
    for r in obj["rules"]:
        if isinstance(r, dict) and r.get("namespace") == namespace:
            if r.get("value") == value:
                return list(r["meanings"])
            if "value" not in r:
                best = list(r["meanings"])
    return best


def load_ambiguity(path):
    return sources.load_canonical(path, "ambiguity")
