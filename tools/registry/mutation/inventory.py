"""Unambiguous inventory of the mutants (standard library only).

    python mutation/inventory.py check                      static checks of the specs: unique ids, no retired id, every pattern present exactly once
    python mutation/inventory.py report RESULTS_DIR... --out FILE.md   merge the per-spec results of one or more platforms into one table

The numbers in any report come from `report`, never from adding up console output by hand. A result file is accepted only for the exact spec it was run
against (SHA-256 of the spec) and must cover exactly the ids of that spec.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "mutation" / "specs"
RETIRED = ROOT / "mutation" / "retired.json"
STATUSES = ("KILLED", "SURVIVED-EQUIVALENT", "SURVIVED-PLATFORM-SPECIFIC", "SURVIVED-GAP", "NOT-APPLIED")


def load_specs(specs_dir: Path = SPECS) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(specs_dir.glob("*.json"))}


def check(specs: dict, retired: list, root: Path = ROOT) -> list:
    out = []
    seen = {}
    for name, spec in specs.items():
        for key in ("tests", "mutants"):
            if key not in spec:
                out.append(f"{name}: no '{key}'")
        for t in spec.get("tests", []):
            if not (root / (t.replace(".", "/") + ".py")).is_file():
                out.append(f"{name}: test module {t} does not exist")
        for m in spec.get("mutants", []):
            mid = m.get("id", "?")
            if mid in seen:
                out.append(f"{mid}: used in both {seen[mid]} and {name} (ids are unique across all specs)")
            seen[mid] = name
            for f in ("id", "file", "old", "new", "note"):
                if not isinstance(m.get(f), str) or (f != "new" and not m[f]):
                    out.append(f"{name}/{mid}: field {f!r} missing or empty")
            if m.get("old") == m.get("new"):
                out.append(f"{name}/{mid}: the mutation changes nothing")
            if "equivalent" in m and (not isinstance(m["equivalent"], str) or len(m["equivalent"]) < 20):
                out.append(f"{name}/{mid}: an equivalence claim needs a reason")
            ps = m.get("platform_specific")
            if ps is not None and not (isinstance(ps, dict) and set(ps) == {"survives_on", "reason"} and ps["survives_on"] and isinstance(ps["reason"], str) and ps["reason"]):
                out.append(f"{name}/{mid}: platform_specific must be {{survives_on: [...], reason: ...}}")
            if "equivalent" in m and ps is not None:
                out.append(f"{name}/{mid}: both equivalent and platform_specific")
            target = root / m.get("file", "")
            if not target.is_file():
                out.append(f"{name}/{mid}: file {m.get('file')} does not exist")
            else:
                n = target.read_text(encoding="utf-8").count(m.get("old", "\0"))
                if n != 1:
                    out.append(f"{name}/{mid}: the pattern occurs {n} times in {m['file']} (must be exactly once)")
    for r in retired:
        if r["id"] in seen:
            out.append(f"{r['id']}: retired ({r['spec']}) but still present in {seen[r['id']]}: ids are never reused")
    return out


def report(specs: dict, retired: list, results_dirs: list, spec_dir: Path = SPECS) -> tuple:
    """-> (markdown, problems). One column per platform; every result file must belong to the current spec."""
    problems = []
    by_platform = {}
    for d in results_dirs:
        for p in sorted(Path(d).glob("*.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            name = Path(r["spec"]).stem
            spec_file = spec_dir / r["spec"]
            if name not in specs:
                problems.append(f"{p.name}: result for an unknown spec {r['spec']}")
                continue
            if hashlib.sha256(spec_file.read_bytes()).hexdigest() != r["spec_sha256"]:
                problems.append(f"{p.name}: the result was produced against another version of the spec (stale)")
                continue
            ids = [x["id"] for x in r["results"]]
            want = [m["id"] for m in specs[name]["mutants"]]
            if sorted(ids) != sorted(want):
                problems.append(f"{p.name}: the results do not cover exactly the ids of the spec")
                continue
            by_platform.setdefault((r["platform"], r["python"]), {})[name] = {x["id"]: x["status"] for x in r["results"]}
    platforms = sorted(by_platform)
    lines = ["# Mutant inventory", "", f"Specs: {len(specs)}; mutants: {sum(len(s['mutants']) for s in specs.values())}; retired ids: {len(retired)}.", ""]
    head = "| spec | id | file | declared | " + " | ".join(f"{pl} py{py}" for pl, py in platforms) + " |"
    lines += [head, "|" + "---|" * (4 + len(platforms))]
    totals = {pk: {s: 0 for s in STATUSES} for pk in platforms}
    for name, spec in specs.items():
        for m in spec["mutants"]:
            declared = "equivalent" if "equivalent" in m else ("platform-specific" if "platform_specific" in m else "")
            cells = []
            for pk in platforms:
                st = by_platform[pk].get(name, {}).get(m["id"])
                if st is None:
                    cells.append("NOT RUN")
                    continue
                totals[pk][st] += 1
                cells.append(st)
                if st in ("SURVIVED-GAP", "NOT-APPLIED"):
                    problems.append(f"{name}/{m['id']} {pk}: {st}")
                if st == "SURVIVED-EQUIVALENT" and "equivalent" not in m:
                    problems.append(f"{name}/{m['id']} {pk}: survived without a declaration")
            lines.append(f"| {name} | {m['id']} | {m['file']} | {declared} | " + " | ".join(cells) + " |")
    lines += ["", "## Totals", "", "| status | " + " | ".join(f"{pl} py{py}" for pl, py in platforms) + " |", "|" + "---|" * (1 + len(platforms))]
    for s in STATUSES:
        lines.append(f"| {s} | " + " | ".join(str(totals[pk][s]) for pk in platforms) + " |")
    lines += ["", "## Retired ids (never reused)", ""] + [f"* `{r['id']}` ({r['spec']}): {r['reason']}" for r in retired]
    return "\n".join(lines) + "\n", problems


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    specs, retired = load_specs(), json.loads(RETIRED.read_text(encoding="utf-8"))["retired"]
    if a[:1] == ["check"]:
        problems = check(specs, retired)
        for p in problems:
            print("PROBLEM:", p)
        print(f"inventory check: {'FAIL' if problems else 'OK'} ({sum(len(s['mutants']) for s in specs.values())} mutants in {len(specs)} specs, {len(retired)} retired ids)")
        return 1 if problems else 0
    if a[:1] == ["report"] and "--out" in a:
        out = Path(a[a.index("--out") + 1])
        dirs = [x for x in a[1:a.index("--out")]]
        md, problems = report(specs, retired, dirs)
        out.write_text(md, encoding="utf-8", newline="\n")
        for p in problems:
            print("PROBLEM:", p)
        print(f"report written: {out} ({'FAIL' if problems else 'OK'})")
        return 1 if problems else 0
    print(__doc__)
    return 3


if __name__ == "__main__":
    sys.exit(main())
