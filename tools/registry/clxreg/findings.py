"""Shared finding record. Classes follow the proposal: DATA_ERROR blocks, EVIDENCE_MISSING blocks a claim, ADVISORY never blocks."""
from __future__ import annotations

from dataclasses import dataclass

DATA_ERROR = "DATA_ERROR"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
ADVISORY = "ADVISORY"
CLASSES = (DATA_ERROR, EVIDENCE_MISSING, ADVISORY)


@dataclass(frozen=True)
class Finding:
    cls: str
    code: str
    record: str
    message: str

    def __post_init__(self):
        if self.cls not in CLASSES:
            raise ValueError(f"unknown finding class {self.cls!r}")

    def line(self) -> str:
        return f"{self.cls:<16} {self.code:<6} {self.record}  {self.message}"


def data_error(code: str, record: str, message: str) -> Finding:
    return Finding(DATA_ERROR, code, record, message)


def advisory(code: str, record: str, message: str) -> Finding:
    return Finding(ADVISORY, code, record, message)


def blocking(findings) -> bool:
    return any(f.cls == DATA_ERROR for f in findings)


def evidence_missing(code: str, record: str, message: str) -> Finding:
    return Finding(EVIDENCE_MISSING, code, record, message)
