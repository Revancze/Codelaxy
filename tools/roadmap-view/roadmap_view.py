#!/usr/bin/env python3
"""roadmap_view - a read-only, translatable HTML view of Codelaxy-Roadmap.ods.

    roadmap_view.py status                    how much of each language pack is translated, and what is missing
    roadmap_view.py merge CHUNK.json          add translations ({"<index>": "text"}) to lang/cs.src.json, validated
    roadmap_view.py build  [--ods F] [--out D]   write D/Codelaxy-Roadmap.html and D/lang/<code>.js
    roadmap_view.py check  [--ods F] [--out D]   prove the generated files belong to this ODS and are consistent
    roadmap_view.py watch  [--ods F] [--out D]   rebuild automatically whenever the ODS is saved (e.g. in LibreOffice)

The ODS is only ever opened for reading. Its SHA-256 and git blob id are taken before and after
every run and compared; a run that sees a difference stops with an error.
Python standard library only.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import rv_ods
import rv_text

HERE = Path(__file__).resolve().parent
_LOOSE_ODS = HERE / "input" / "Codelaxy-Roadmap.ods"  # a loose copy next to the tool (used by the test harness)
REPO_ROOT = HERE.parents[1]  # tools/roadmap-view -> repository root
DEFAULT_ODS = _LOOSE_ODS if _LOOSE_ODS.exists() else REPO_ROOT / "docs" / "Codelaxy-Roadmap.ods"
DEFAULT_OUT = HERE / "out" if _LOOSE_ODS.exists() else REPO_ROOT / "docs" / "roadmap-view"
LANG_DIR = HERE / "lang"


# --------------------------------------------------------------------------- strings


def collect_strings(wb: rv_ods.Workbook) -> "collections.OrderedDict[str, list[str]]":
    """Unique displayed texts of string cells -> the cell keys (SHEET!A1) that show them, in document order."""
    out: collections.OrderedDict[str, list[str]] = collections.OrderedDict()
    for sh in wb.sheets:
        for row in sh.rows:
            for c in row:
                if c is not None and c.kind == "string" and c.text:
                    out.setdefault(rv_text.normalize(c.text), []).append(f"{sh.name}!{c.address}")
    return out


def translatable_strings(strings) -> list[tuple[int, str]]:
    return [(i, t) for i, t in enumerate(strings) if rv_text.is_translatable(t)]


def load_source(lang: str) -> dict:
    path = LANG_DIR / f"{lang}.src.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"lang": lang, "name": {"cs": "Čeština"}.get(lang, lang), "entries": {}}


def save_source(data: dict) -> None:
    LANG_DIR.mkdir(exist_ok=True)
    path = LANG_DIR / f"{data['lang']}.src.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- commands


def open_workbook(path: Path) -> tuple[rv_ods.Workbook, str, str]:
    """Read the workbook and return it with the identity taken BEFORE reading."""
    before = (rv_ods.sha256_file(str(path)), rv_ods.git_blob_id(str(path)))
    wb = rv_ods.read_workbook(str(path))
    return wb, before[0], before[1]


def assert_unchanged(path: Path, sha: str, blob: str) -> None:
    after = (rv_ods.sha256_file(str(path)), rv_ods.git_blob_id(str(path)))
    if after != (sha, blob):
        raise SystemExit(f"ERROR: {path} changed while the tool ran (sha256 {sha} -> {after[0]}). Aborting.")


def cmd_status(args) -> int:
    wb, sha, blob = open_workbook(Path(args.ods))
    strings = collect_strings(wb)
    todo = translatable_strings(strings)
    src = load_source(args.lang)["entries"]
    done = [(i, t) for i, t in todo if rv_text.text_hash(t) in src and src[rv_text.text_hash(t)]["en"] == t]
    stale = [(i, t) for i, t in todo if rv_text.text_hash(t) in src and src[rv_text.text_hash(t)]["en"] != t]
    missing = [(i, t) for i, t in todo if rv_text.text_hash(t) not in src]
    print(f"ODS sha256 {sha[:16]}  blob {blob[:8]}  unique strings {len(strings)}  translatable {len(todo)}")
    print(f"[{args.lang}] translated {len(done)}   missing {len(missing)}   stale {len(stale)}")
    for i, t in missing[: args.show]:
        print(f"  {i}|{t.replace(chr(10), ' ⏎ ')}")
    if len(missing) > args.show:
        print(f"  ... and {len(missing) - args.show} more")
    assert_unchanged(Path(args.ods), sha, blob)
    return 0 if not missing and not stale else 1


def cmd_merge(args) -> int:
    wb, sha, blob = open_workbook(Path(args.ods))
    strings = list(collect_strings(wb))
    chunk = json.loads(Path(args.chunk).read_text(encoding="utf-8"))
    data = load_source(args.lang)
    bad = 0
    for key, cs in chunk.items():
        i = int(key)
        if not 0 <= i < len(strings):
            print(f"  #{key}: no such string index")
            bad += 1
            continue
        en = strings[i]
        problems = rv_text.check_translation(en, cs)
        if problems:
            print(f"  #{key}: {'; '.join(problems)}\n      EN: {en[:140]!r}\n      CS: {cs[:140]!r}")
            bad += 1
            continue
        data["entries"][rv_text.text_hash(en)] = {"en": en, "cs": cs}
    if bad:
        print(f"{bad} entr{'y' if bad == 1 else 'ies'} rejected; nothing from this chunk was saved.")
        return 1
    save_source(data)
    print(f"merged {len(chunk)} entries; total {len(data['entries'])}")
    assert_unchanged(Path(args.ods), sha, blob)
    return 0


def generate(ods: Path, langs: list[str]) -> tuple[dict[str, str], dict]:
    """Render everything in memory: {relative path: text}, plus a report. Touches no file."""
    import rv_html

    wb, sha, blob = open_workbook(ods)
    files: dict[str, str] = {}
    pack_files, report = [], {"missing": {}, "translated": {}}
    for lang in langs:
        src = load_source(lang)
        pack, info = rv_html.build_pack(wb, src)
        files[f"lang/{lang}.js"] = rv_html.pack_js(pack)
        pack_files.append({"code": lang, "name": src["name"], "file": f"lang/{lang}.js"})
        report["missing"][lang] = info["missing_cells"]
        report["translated"][lang] = info["translated_cells"]
    page, config = rv_html.render_html(wb, pack_files, ods.name)
    files["Codelaxy-Roadmap.html"] = page
    report.update(config["counts"], sha256=sha, blob=blob)
    assert_unchanged(ods, sha, blob)
    return files, report


def cmd_build(args) -> int:
    ods, out = Path(args.ods).resolve(), Path(args.out).resolve()
    if out == ods or ods.is_relative_to(out):
        raise SystemExit("ERROR: the output folder must not contain or equal the ODS source.")
    files, report = generate(ods, [args.lang])
    for rel, text in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(files)} files to {out}")
    print(f"  sha256 {report['sha256']}  blob {report['blob'][:8]}")
    for lang in report["translated"]:
        print(f"  [{lang}] translated cells {report['translated'][lang]}, missing {len(report['missing'][lang])}")
    print(f"  translatable cells {report['translatable_cells']}, refused links {report['refused_links']}, "
          f"notes omitted {report['notes_omitted']}, validations ignored {report['validations_ignored']}")
    return 1 if any(report["missing"].values()) else 0


def cmd_check(args) -> int:
    """Generation check: do the files on disk equal what THIS ods produces right now?"""
    ods, out = Path(args.ods).resolve(), Path(args.out).resolve()
    files, report = generate(ods, [args.lang])
    bad = 0
    for rel, text in files.items():
        target = out / rel
        if not target.exists():
            print(f"MISSING {rel}")
            bad += 1
        elif target.read_text(encoding="utf-8") != text:
            print(f"STALE   {rel}: differs from what the current ODS produces (rebuild it)")
            bad += 1
        else:
            print(f"ok      {rel}")
    if any(report["missing"].values()):
        print(f"INCOMPLETE translation: {sum(len(v) for v in report['missing'].values())} cells without a current translation")
        bad += 1
    return 1 if bad else 0


def write_if_changed(files: dict[str, str], out: Path) -> int:
    """Write only files whose content differs (so an open browser tab is not reloaded for nothing)."""
    changed = 0
    for rel, text in files.items():
        target = out / rel
        if target.exists() and target.read_text(encoding="utf-8") == text:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        changed += 1
    return changed


def write_todo(ods: Path, lang: str, todo: Path) -> int:
    """List the English texts that have no current translation ({"<index>": text}); remove the list when complete."""
    wb, sha, blob = open_workbook(ods)
    src = load_source(lang)["entries"]
    missing = {str(i): t for i, t in translatable_strings(collect_strings(wb)) if rv_text.text_hash(t) not in src}
    assert_unchanged(ods, sha, blob)
    if missing:
        todo.parent.mkdir(parents=True, exist_ok=True)
        todo.write_text(json.dumps(missing, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    elif todo.exists():
        todo.unlink()
    return len(missing)


class Watcher:
    """Rebuild the view whenever the workbook is saved. The workbook is only ever read.

    LibreOffice saves by writing a new file, so a change is acted on only after it has stayed the same
    for two polls, and a half-written file (bad zip, bad XML) is simply retried on the next poll.
    """

    def __init__(self, ods: Path, out: Path, lang: str, todo: Path):
        self.ods, self.out, self.lang, self.todo = ods, out, lang, todo
        self.built_sig = self.seen_sig = None

    def signature(self):
        try:
            st = self.ods.stat()
        except OSError:
            return None  # mid-replace
        return (st.st_size, st.st_mtime_ns)

    def rebuild(self) -> str:
        sig = self.signature()
        files, report = generate(self.ods, [self.lang])
        written = write_if_changed(files, self.out)
        missing = write_todo(self.ods, self.lang, self.todo)
        self.built_sig = self.seen_sig = sig
        line = (f"rebuilt ({written} file{'s' if written != 1 else ''} changed) - {self.lang}: "
                f"{report['translated'][self.lang]} translated, {missing} need a translation")
        if missing:
            line += f"\n  changed cells show 'outdated/missing' until translated; list: {self.todo}"
        return line

    def step(self) -> str | None:
        sig = self.signature()
        if sig is None or sig == self.built_sig:
            self.seen_sig = sig
            return None
        if sig != self.seen_sig:  # just changed: wait one more poll so a save in progress can finish
            self.seen_sig = sig
            return None
        try:
            return self.rebuild()
        except (OSError, ValueError, KeyError, SystemExit, zipfile.BadZipFile, ET.ParseError) as e:
            return f"waiting for a readable workbook ({type(e).__name__}); will retry"


def cmd_watch(args) -> int:
    ods, out = Path(args.ods).resolve(), Path(args.out).resolve()
    if out == ods or ods.is_relative_to(out):
        raise SystemExit("ERROR: the output folder must not contain or equal the ODS source.")
    todo = Path(args.todo) if args.todo else Path(tempfile.gettempdir()) / "roadmap-view" / f"todo.{args.lang}.json"
    w = Watcher(ods, out, args.lang, todo)
    print(f"watching {ods}\n  output {out}\n  Ctrl+C to stop. Save the workbook in LibreOffice, then press F5 in the browser.")
    print(" ", w.rebuild())
    try:
        while True:
            time.sleep(args.interval)
            msg = w.step()
            if msg:
                print(time.strftime("%H:%M:%S"), msg, flush=True)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="roadmap_view", description=__doc__.split("\n")[0])
    ap.add_argument("--ods", default=str(DEFAULT_ODS))
    ap.add_argument("--lang", default="cs")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--show", type=int, default=25)
    m = sub.add_parser("merge")
    m.add_argument("chunk")
    sub.add_parser("build")
    sub.add_parser("check")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=float, default=2.0)
    w.add_argument("--todo", default="")
    args = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return {"status": cmd_status, "merge": cmd_merge, "build": cmd_build, "check": cmd_check,
            "watch": cmd_watch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
