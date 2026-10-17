#!/usr/bin/env python3
"""Codelaxy M1/F3 warning gate, SARIF 2.1, stdlib only.

Canonical identity: (project, repository-relative source path, diagnostic ID).
Line/column and localized diagnostic message are intentionally ignored.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

PROJECT_FILES = (
    "src/Codelaxy.Contracts/Codelaxy.Contracts.csproj",
    "src/Codelaxy.Core/Codelaxy.Core.csproj",
    "src/Codelaxy.Git/Codelaxy.Git.csproj",
    "src/Codelaxy.Cli/Codelaxy.Cli.csproj",
    "tests/Codelaxy.ProcessTestHelper/Codelaxy.ProcessTestHelper.csproj",
    "tests/Codelaxy.Tests/Codelaxy.Tests.csproj",
)
PROJECTS = tuple(Path(project).stem for project in PROJECT_FILES)
PROJECT_SET = set(PROJECTS)
DIAGNOSTIC_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]+$")


class GateError(ValueError):
    pass


def require(condition: bool, explanation: str) -> None:
    if not condition:
        raise GateError(explanation)


def normalize_root(source_root: str) -> str:
    normalized = source_root.replace("\\", "/").rstrip("/")
    require(bool(normalized), "Empty repository/source root")
    return normalized


def relative_source(file_uri: str, source_root: str) -> str:
    require(isinstance(file_uri, str), "SARIF file URI is missing")
    parts = urlsplit(file_uri)
    require(parts.scheme == "file" and parts.netloc in ("", "localhost"),
            f"Untrusted SARIF URI scheme/host: {file_uri!r}")
    require(not parts.query and not parts.fragment, "SARIF source URI has query/fragment")
    decoded = unquote(parts.path)
    require("\\" not in decoded and "\x00" not in decoded, "Invalid SARIF source path")
    # file:///C:/... -> C:/...; Linux file:///home/... remains absolute.
    if re.match(r"^/[A-Za-z]:/", decoded):
        decoded = decoded[1:]
    require(all(piece not in ("", ".", "..") for piece in decoded.split("/")[1:]),
            f"Unnormalized SARIF source URI: {file_uri!r}")
    root = normalize_root(source_root)
    windows = bool(re.match(r"^[A-Za-z]:/", root))
    compared = decoded.casefold() if windows else decoded
    expected = (root + "/").casefold() if windows else root + "/"
    require(compared.startswith(expected),
            f"SARIF source outside repository: {file_uri!r}")
    relative = decoded[len(root) + 1:]
    require(relative.startswith(("src/", "tests/")) and relative.endswith(".cs"),
            f"Unexpected diagnostic source: {relative!r}")
    return relative


def valid_entry(entry: object) -> tuple[str, str, str, int]:
    require(isinstance(entry, dict), "Baseline warning must be an object")
    require(set(entry) == {"project", "path", "id", "count"},
            f"Unexpected baseline fields: {entry!r}")
    project, path, rule, count = (entry[k] for k in ("project", "path", "id", "count"))
    require(isinstance(project, str) and project in PROJECT_SET,
            f"Unknown baseline project: {project!r}")
    require(isinstance(path, str) and path.startswith(("src/", "tests/"))
            and path.endswith(".cs") and "\\" not in path
            and all(part not in ("", ".", "..") for part in path.split("/")),
            f"Invalid baseline path: {path!r}")
    require(isinstance(rule, str) and DIAGNOSTIC_ID.fullmatch(rule) is not None,
            f"Invalid baseline rule ID: {rule!r}")
    require(type(count) is int and count > 0, f"Invalid baseline count: {count!r}")
    return project, path, rule, count


def load_baseline(path: Path) -> Counter[tuple[str, str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise GateError(f"Baseline cannot be read: {ex}") from ex
    require(isinstance(raw, dict) and set(raw) == {"schema", "projects", "warnings"}
            and type(raw["schema"]) is int and raw["schema"] == 1,
            "Invalid baseline schema")
    require(raw["projects"] == list(PROJECTS), "Baseline project manifest changed")
    require(isinstance(raw["warnings"], list), "Baseline warnings must be a list")
    counts: Counter[tuple[str, str, str]] = Counter()
    for item in raw["warnings"]:
        project, path, rule, count = valid_entry(item)
        key = (project, path, rule)
        require(key not in counts, f"Duplicate baseline key: {key!r}")
        counts[key] = count
    return counts


def load_diagnostics(sarif_dir: Path, source_root: str) -> Counter[tuple[str, str, str]]:
    require(sarif_dir.is_dir(), f"Missing SARIF directory: {sarif_dir}")
    filenames = {path.name for path in sarif_dir.iterdir() if path.is_file()}
    expected_files = {name + ".sarif" for name in PROJECTS}
    require(filenames == expected_files,
            f"Missing/unexpected SARIF files: missing={sorted(expected_files-filenames)}; "
            f"extra={sorted(filenames-expected_files)}")
    observed: Counter[tuple[str, str, str]] = Counter()
    for project in PROJECTS:
        file = sarif_dir / (project + ".sarif")
        try:
            record = json.loads(file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as ex:
            raise GateError(f"Invalid SARIF {project}: {ex}") from ex
        require(isinstance(record, dict) and record.get("version") == "2.1.0",
                f"{project}: missing SARIF 2.1.0 header")
        runs = record.get("runs")
        require(isinstance(runs, list) and len(runs) == 1 and isinstance(runs[0], dict),
                f"{project}: expected exactly one SARIF run")
        run = runs[0]
        driver = run.get("tool", {}).get("driver", {})
        require(isinstance(driver, dict) and isinstance(driver.get("name"), str)
                and "Microsoft (R) Visual C#" in driver["name"]
                and isinstance(driver.get("rules"), list) and len(driver["rules"]) > 0,
                f"{project}: compiler/analyzer manifest missing")
        invocations = run.get("invocations")
        require(isinstance(invocations, list) and len(invocations) == 1
                and isinstance(invocations[0], dict)
                and invocations[0].get("executionSuccessful") is True,
                f"{project}: compiler execution not proven successful")
        results = run.get("results")
        require(isinstance(results, list), f"{project}: results array missing")
        for i, result in enumerate(results):
            require(isinstance(result, dict), f"{project}: result {i} is not an object")
            level = result.get("level")
            require(level in ("note", "warning", "error"),
                    f"{project}: unknown diagnostic level {level!r}")
            if level == "note":
                continue
            require(level != "error", f"{project}: compiler error in SARIF result {i}")
            rule = result.get("ruleId")
            require(isinstance(rule, str) and DIAGNOSTIC_ID.fullmatch(rule) is not None,
                    f"{project}: missing/invalid rule ID at result {i}")
            locations = result.get("locations")
            require(isinstance(locations, list) and len(locations) == 1
                    and isinstance(locations[0], dict),
                    f"{project}: missing/ambiguous source location for {rule}")
            uri = locations[0].get("physicalLocation", {}).get("artifactLocation", {}).get("uri")
            rel = relative_source(uri, source_root)
            observed[(project, rel, rule)] += 1
    return observed


def check(baseline_file: Path, sarif_dir: Path, source_root: str) -> None:
    allowed = load_baseline(baseline_file)
    actual = load_diagnostics(sarif_dir, source_root)
    violations = actual - allowed
    if violations:
        details = "\n".join(
            f"  {project} | {path} | {rule}: +{over} "
            f"(actual {actual[(project, path, rule)]}, allowed {allowed[(project, path, rule)]})"
            for (project, path, rule), over in sorted(violations.items())
        )
        raise GateError("Warning regression(s):\n" + details)
    print(f"F3 WARNING GATE: PASS | {sum(actual.values())} warnings | "
          f"{len(actual)} locations/rules | {len(PROJECTS)}/{len(PROJECTS)} SARIF")
    for (project, path, rule), count in sorted((allowed - actual).items()):
        print(f"  IMPROVED: {project} | {path} | {rule}: -{count}")


def run_dotnet(args: list[str], log_file: Path, cwd: Path) -> None:
    with log_file.open("w", encoding="utf-8") as log:
        proc = subprocess.run(["dotnet", *args], cwd=cwd, stdout=log,
                              stderr=subprocess.STDOUT, check=False)
    if proc.returncode:
        tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-45:]
        raise GateError(f"dotnet build failed ({proc.returncode}): {log_file}\n" + "\n".join(tail))
    print("BUILD PASS:", log_file.name)


def collect(repo_root: Path, out_dir: Path) -> Path:
    require((repo_root / "Codelaxy.sln").is_file(), "Codelaxy.sln missing")
    require(not out_dir.exists(), f"Output directory already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    sarif_dir = out_dir / "sarif"
    sarif_dir.mkdir()
    build_flags = ["--configuration", "Debug", "--no-restore", "--no-incremental",
                   "--disable-build-servers", "--tl:off", "--nologo", "--verbosity", "minimal",
                   "-p:RunAnalyzers=true", "-p:RunAnalyzersDuringBuild=true"]
    run_dotnet(["build", "Codelaxy.sln", *build_flags], out_dir / "00-build.log", repo_root)
    for path in PROJECT_FILES:
        project = Path(path).stem
        sarif_path = (sarif_dir / (project + ".sarif")).resolve()
        # MSBuild treats comma as a list separator; %2C is MSBuild escaping.
        run_dotnet(["build", path, *build_flags, "--no-dependencies",
                    f"-p:ErrorLog={sarif_path}%2Cversion=2.1"],
                   out_dir / (project + ".log"), repo_root)
        require(sarif_path.is_file() and sarif_path.stat().st_size > 0,
                f"Missing/empty compiler SARIF for {project}")
    return sarif_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "collect-and-check"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-root", help="Original checkout root for offline archived SARIF (check mode only)")
    parser.add_argument("--sarif-dir", type=Path, help="Required in check mode")
    parser.add_argument("--output-dir", type=Path, help="Build evidence output outside repository")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        require(not (args.source_root and args.mode != "check"),
                "--source-root applies only to offline check")
        if args.mode == "collect-and-check":
            require(args.sarif_dir is None, "--sarif-dir cannot be set when collecting")
            output_dir = args.output_dir or (Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir()))
                                              / f"codelaxy-f3-{os.getpid()}")
            sarif = collect(repo_root, output_dir.resolve())
        else:
            require(args.sarif_dir is not None, "--sarif-dir required in check mode")
            sarif = args.sarif_dir
        check(args.baseline, sarif, args.source_root or str(repo_root))
    except (GateError, OSError) as ex:
        print(f"F3 WARNING GATE: FAIL | {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
