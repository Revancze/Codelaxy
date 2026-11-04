"""IMP2-07a - literal capture of the original states, references and result phrases of a source (the mandatory minimum of IMP2-07).

Nothing is interpreted: a token is recorded because its characters match a syntactic pattern, with the name of the pattern, never with a meaning.
The ledger gives every one of them the disposition UNCLASSIFIED_LABEL ("exists, not interpreted"). Distinguishing a hash from a word, an OPEN inside
a legend from one outside, or attaching a state to a requirement is IMP2-07b (deferred) and stays non-binding.
Known limits (by design, reported): a commit hash written only with decimal digits is recognised only when it has exactly seven characters;
a hex string longer than 64 characters is not a hash here; test names are recognised by the suffix `Tests`/`Test` or the prefix `test_`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .patterns import boundary_matches

STATE_WORD, REFERENCE, RESULT_PHRASE = "STATE_WORD", "REFERENCE", "RESULT_PHRASE"
CLASSES = (STATE_WORD, REFERENCE, RESULT_PHRASE)

STATE_WORDS = ("DONE", "PARTIAL", "PLANNED", "BLOCKED", "UNKNOWN", "OPEN", "CLOSED", "FIXED", "VERIFIED", "ASSERTED", "PROVISIONAL", "RATIFIED",
               "PROPOSED", "DRAFT", "HISTORICAL", "REJECTED", "SUPERSEDED", "WITHDRAWN", "NOT RUN")

_PATTERNS = [
    (STATE_WORD, "state-word", re.compile("|".join(re.escape(w) for w in sorted(STATE_WORDS, key=lambda w: (-len(w), w))))),
    (REFERENCE, "pr", re.compile(r"(?:PR )?#[0-9]{1,5}")),
    (REFERENCE, "hash", re.compile(r"(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}")),
    (REFERENCE, "hash-digits-7", re.compile(r"[0-9]{7}")),
    (REFERENCE, "ci-run", re.compile(r"(?:CI )?run [0-9]{8,}")),
    (REFERENCE, "file-line", re.compile(r"[A-Za-z0-9_./\\-]+\.(?:cs|md|py|json|yml|yaml|txt|sdoc|ods):[0-9]+(?:-[0-9]+)?")),
    (REFERENCE, "test-name", re.compile(r"[A-Z][A-Za-z0-9]*Tests?(?:\.[A-Za-z0-9_]+)?|test_[a-z0-9_]+")),
    (RESULT_PHRASE, "n-of-n", re.compile(r"[0-9]+ of [0-9]+")),
    (RESULT_PHRASE, "pass", re.compile(r"PASS(?:ED)?")),
    (RESULT_PHRASE, "fail", re.compile(r"FAIL(?:ED)?")),
]


@dataclass(frozen=True)
class Literal:
    start: int
    end: int
    text: str
    cls: str
    patterns: tuple          # names of the syntactic patterns that matched exactly this span


def scan_literals(text: str) -> list:
    found = {}
    for cls, name, rx in _PATTERNS:
        for m in boundary_matches(rx, text):
            found.setdefault((m.start(), m.end(), cls), set()).add(name)
    return [Literal(s, e, text[s:e], cls, tuple(sorted(names))) for (s, e, cls), names in sorted(found.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]))]
