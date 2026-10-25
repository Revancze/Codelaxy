"""Text rules of the roadmap viewer: normalisation, hashing, and protected tokens.

Protected tokens are things a translator must never touch: IDs (P1.2-M1.4, OPEN-16, E1),
status words (DONE, PLANNED ...), file names and paths, identifiers (GitSnapshotBuilder,
NOT_REQUIRED), commit hashes, git commands, backticked spans, [D]/[I] tags, verbatim quotes
and the symbols used in the test matrix. They are found STRUCTURALLY here, at build time, and
handed to translators as placeholders, never as an instruction ("do not translate this").
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# status / type / verdict vocabulary written in capitals in the workbook
VOCAB = (
    "IN PROGRESS", "DONE", "PARTIAL", "PLANNED", "BLOCKED", "UNKNOWN", "OPEN", "DIRECTION", "STEP", "ITEM",
    "EXTRA", "EXIT", "FINDING", "DECISION", "TEST", "PHASE", "CAPABILITY", "RATIFIED", "GRANTED", "REUSED",
    "FAILED", "EXECUTED", "PASSED", "UNUSABLE", "INCOMPLETE", "VALID", "BUILD", "REQUIRED", "PROPOSED",
    "OVERVIEW", "MICROMAP", "LONGTERMMAP", "RULES", "DECIDED", "DEFERRED", "REJECTED",
)
_VOCAB_RE = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(v) for v in sorted(VOCAB, key=len, reverse=True)) + r")(?![\w-])")

# order matters: at the same start position the earlier alternative wins
_PROTECT = re.compile(
    "|".join([
        r"`[^`\n]+`",  # backticked code
        r"\[(?:D|I)(?::[^\]\n]*)?\]",  # [D], [I], [D: order]
        r"https?://[^\s)\]]+",  # URLs
        r"(?<!\w)'[^'\n]{2,160}'(?!\w)",  # verbatim quotes ('ratified', 'D+I')
        r"(?:[\w.\-]+/)+[\w.\-]*\w(?::\d+(?:-\d+)?)?",  # paths: docs/roadmap.md, tools/ci/x.py
        r"\b[\w\-]+\.(?:md|ods|cs|py|yml|yaml|json|csproj|sh|txt)(?::\d+(?:-\d+)?)?",  # file names
        r"\bgit (?:hash-object|ls-files|rev-parse|rev-list|status|log|diff|show|config|worktree|stash|fetch|push|pull|commit|checkout|switch|clean|reset|rebase|merge|add|restore|branch|tag"
        r"|cat-file|update-index|for-each-ref|describe|init|clone|gc|prune|reflog|apply|cherry-pick|bisect|blame|grep|mv|rm|archive|bundle|remote|submodule|symbolic-ref"
        r"|write-tree|read-tree|commit-tree|show-ref|version)(?: --?[a-z][a-z-]*)*",  # git hash-object --stdin-paths
        r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b",  # commit ids
        r"\bP\d+(?:\.\d+)+(?:-[A-Z]+\d*[a-z]?(?:\.[A-Z]?\d+)?)*",  # P1.2, P1.2-M1.4, P1.2-M4.T01, P1.2-MSYS2-COMPAT
        r"\b(?:OPEN|CAP|DIR|OD)-\d+\b",  # OPEN-16, CAP-3
        r"\b[A-Z]{2,5}-\d+\b",  # THR-014
        r"\bNOT_REQUIRED\b",
        r"\bPRs? #\d+(?:–#?\d+)?",  # PR #7, PRs #6-#9
        r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9…]+)+\b(?::\d+(?:-\d+)?)?",  # snake_case / SCREAMING_CASE identifiers
        r"[A-Za-z_][\w…]*:\d+(?:-\d+)?",  # IndexGolden001...:77, matrix:105
        r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*)+\b",  # Codelaxy.Git
        r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b",  # PascalCase identifiers
        r"\b[a-z][a-z0-9]*\.[A-Za-z][A-Za-z0-9]*(?:=\w+)?\b",  # bool.Parse, core.ignoreCase=false
        r"\b(?:windows|ubuntu)-[\w.]*\w",  # CI runner names
        r"\b(?:UCRT64|dotnet|ccache|Ninja|pytest|ruff|shellcheck|shfmt|bats|my-cpu-router|CPU Router|MrProper|StatusMan|Codelaxy)\b",  # product and tool names
        r"\b[A-Z]{1,3}\d+[A-Za-z]?\d*(?:\.\d+)?\b",  # E1, T1, F8, M3a, M1.4, S104, CA2025, I12
        r"\b[A-Z](?: / [A-Z])+\b",  # H / I / S / W
        r"\b[A-Z]\+[A-Z]\b",  # D+I
        r"[❓❌✅➖\U0001F4DD]+",  # test-matrix marks
    ])
)

_CAPS_NEIGHBOUR_BEFORE = re.compile(r"[A-Z]{2,}[ ]$")
_CAPS_NEIGHBOUR_AFTER = re.compile(r"^[ ][A-Z]{2,}\b")


def normalize(text: str) -> str:
    """The exact form that is hashed: NFC, LF line ends, no trailing blanks per line."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def text_hash(text: str) -> str:
    """16 hex chars of SHA-256 over the normalised UTF-8 text (text only, no metadata)."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:16]


def tokenize(text: str) -> list[tuple[bool, str]]:
    """Split into (protected?, piece) so that ''.join(pieces) == text."""
    spans: list[tuple[int, int]] = []
    for m in _PROTECT.finditer(text):
        spans.append((m.start(), m.end()))
    for m in _VOCAB_RE.finditer(text):
        # a status word glued to another ALL-CAPS word is part of a heading ("OPEN BLOCKERS"): translate it
        before, after = text[: m.start()], text[m.end():]
        if _CAPS_NEIGHBOUR_BEFORE.search(before) and not _VOCAB_RE.search(before[-12:]):
            continue
        if _CAPS_NEIGHBOUR_AFTER.match(after) and not _VOCAB_RE.match(after[1:]):
            continue
        spans.append((m.start(), m.end()))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)  # overlapping: keep the union
            continue
        merged.append((s, e))
    out: list[tuple[bool, str]] = []
    pos = 0
    for s, e in merged:
        if s > pos:
            out.append((False, text[pos:s]))
        out.append((True, text[s:e]))
        pos = e
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def protected_tokens(text: str) -> list[str]:
    return sorted(piece for prot, piece in tokenize(text) if prot)


def is_translatable(text: str) -> bool:
    """True when something other than protected tokens, digits and punctuation is left to translate."""
    if len(text.strip()) <= 1:  # a lone letter is a code (the D / I dependency marks), not prose
        return False
    for prot, piece in tokenize(text):
        if not prot and re.search(r"[^\W\d_]", piece):
            return True
    return False


PLACEHOLDER_OPEN, PLACEHOLDER_CLOSE = "⟦", "⟧"  # mathematical white square brackets


def to_placeholders(text: str) -> tuple[str, list[str]]:
    """Replace protected tokens by numbered placeholders for a machine translator."""
    parts, tokens = [], []
    for prot, piece in tokenize(text):
        if prot:
            parts.append(f"{PLACEHOLDER_OPEN}{len(tokens)}{PLACEHOLDER_CLOSE}")
            tokens.append(piece)
        else:
            parts.append(piece)
    return "".join(parts), tokens


def check_translation(en: str, cs: str) -> list[str]:
    """Problems that make a translation unusable: changed tokens, changed paragraph count."""
    problems = []
    if en.count("\n") != cs.count("\n"):
        problems.append(f"paragraph count differs ({en.count(chr(10)) + 1} vs {cs.count(chr(10)) + 1})")
    a, b = protected_tokens(en), protected_tokens(cs)
    if a != b:
        missing = [t for t in a if t not in b or a.count(t) > b.count(t)]
        extra = [t for t in b if t not in a or b.count(t) > a.count(t)]
        if missing:
            problems.append("missing/changed protected: " + ", ".join(sorted(set(missing))))
        if extra:
            problems.append("unexpected protected: " + ", ".join(sorted(set(extra))))
    if not cs.strip():
        problems.append("empty translation")
    return problems
