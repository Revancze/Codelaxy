"""Targeted mutation check (standard library only).

    python -B mutation/run_mutants.py mutation/specs/protect.json [--json results.json]

A spec lists single textual mutants of clxreg modules and the test modules that must kill them. Each mutant is applied to a COPY of
tools/registry (the working tree is never touched), exactly once, and the tests run in the copy. Exit 0 only if every mutant is KILLED or
is declared `equivalent` with a reason and SURVIVES (or declares `platform_specific: {"survives_on": ["linux"], "reason": ...}` and survives on one of those
platforms); a mutant whose pattern is not found exactly once is an error. With --json the result of EVERY mutant is written as data (the inventory is built from it).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(spec_path: Path, json_out: Path | None = None) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    platform = "windows" if os.name == "nt" else "linux"
    results = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    bad = 0
    killed = 0
    # baseline: the UNMUTATED tests must pass in the copy, otherwise "killed" would only mean "the tests were already broken"
    base = Path(tempfile.mkdtemp(prefix="clx-mut-base-"))
    try:
        shutil.copytree(ROOT, base / "registry", ignore=shutil.ignore_patterns("__pycache__", "local", ".git"))
        p0 = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "unittest"] + spec["tests"], cwd=base / "registry", capture_output=True,
                            text=True, encoding="utf-8", env=env)
        if p0.returncode != 0:
            print("BASELINE FAILS - mutation result would be meaningless:\n" + (p0.stderr or p0.stdout)[-800:])
            return 2
    finally:
        shutil.rmtree(base, ignore_errors=True)
    for m in spec["mutants"]:
        tmp = Path(tempfile.mkdtemp(prefix="clx-mut-"))
        try:
            work = tmp / "registry"
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("__pycache__", "local", ".git"))
            target = work / m["file"]
            text = target.read_text(encoding="utf-8")
            n = text.count(m["old"])
            if n != 1:
                print(f'{m["id"]:<5} NOT APPLIED (pattern found {n}x)  {m["note"]}')
                results.append({"id": m["id"], "status": "NOT-APPLIED"})
                bad += 1
                continue
            target.write_text(text.replace(m["old"], m["new"]), encoding="utf-8", newline="\n")
            p = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "unittest"] + spec["tests"], cwd=work, capture_output=True, text=True,
                               encoding="utf-8", env=env)
            survived = p.returncode == 0
            if survived and "equivalent" in m:
                print(f'{m["id"]:<5} SURVIVED (declared equivalent: {m["equivalent"]})  {m["note"]}')
                results.append({"id": m["id"], "status": "SURVIVED-EQUIVALENT"})
            elif survived and platform in m.get("platform_specific", {}).get("survives_on", []):
                print(f'{m["id"]:<5} SURVIVED (platform-specific on {platform}: {m["platform_specific"]["reason"]})  {m["note"]}')
                results.append({"id": m["id"], "status": "SURVIVED-PLATFORM-SPECIFIC"})
            elif survived:
                print(f'{m["id"]:<5} SURVIVED  <-- test gap  {m["note"]}')
                results.append({"id": m["id"], "status": "SURVIVED-GAP"})
                bad += 1
            else:
                print(f'{m["id"]:<5} KILLED   {m["note"]}')
                results.append({"id": m["id"], "status": "KILLED"})
                killed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f'mutants: {len(spec["mutants"])}, killed {killed}, problems {bad}')
    if json_out is not None:
        import hashlib
        out = {"spec": spec_path.name, "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(), "platform": platform,
               "python": sys.version.split()[0], "tests": spec["tests"], "results": results}
        json_out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    out = Path(args[args.index("--json") + 1]) if "--json" in args else None
    sys.exit(run(Path(args[0]), out))
