
"""Adversarial global Git configuration regression for Golden fixtures."""

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "tests" / "Codelaxy.Tests" / "Codelaxy.Tests.csproj"

FILTER = (
    "FullyQualifiedName~GitSnapshotHeadStagedGoldenTests"
    "|FullyQualifiedName~GitSnapshotIndexGoldenTests"
)

CASES = (
    "hooks",
    "template",
    "excludes",
    "attributes",
    "autocrlf",
    "merge_ff",
    "merge_signatures",
    "branch_merge_options",
    "ignore_stat",
    "fsmonitor",
)

# Exact outcome of the Golden filter per platform. The Linux-only symlink theory
# is reported as skipped on Windows; nothing else may be skipped or missing.
EXPECTED_COUNTS = {
    "windows": {"total": 12, "passed": 11, "failed": 0, "skipped": 1},
    "linux": {"total": 13, "passed": 13, "failed": 0, "skipped": 0},
}


def run(args, cwd, env, *, check=True):
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )

    if check and result.returncode:
        raise AssertionError(
            f"Command failed ({result.returncode}): {args}\n"
            f"{result.stdout}"
        )

    return result


def git(args, cwd, env, *, check=True):
    return run(["git", *args], cwd, env, check=check)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def make_environment(directory):
    home = directory / "home"
    home.mkdir()

    env = os.environ.copy()

    for key in list(env):
        if key in {
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_CONFIG_COUNT",
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
        } or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            env.pop(key, None)

    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / "xdg")
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_NOLOGO"] = "1"

    return env, home / ".gitconfig"


def set_global(config, key, value, cwd, env):
    git(
        ["config", "--file", str(config), key, str(value)],
        cwd,
        env,
    )


def init_repo(path, env):
    path.mkdir()
    git(["init", "-q", "-b", "main"], path, env)


def commit(path, env, message):
    git(
        [
            "-c", "user.name=Codelaxy Probe",
            "-c", "user.email=probe@example.invalid",
            "-c", "commit.gpgsign=false",
            "commit", "-qm", message,
        ],
        path,
        env,
    )


def create_conflict(path, env):
    init_repo(path, env)

    git(["config", "--local", "user.name", "Codelaxy Probe"], path, env)
    git(["config", "--local", "user.email", "probe@example.invalid"], path, env)

    file = path / "conflict.txt"
    file.write_text("base\n", encoding="utf-8")
    git(["add", "conflict.txt"], path, env)
    commit(path, env, "base")

    git(["switch", "-qc", "theirs"], path, env)
    file.write_text("theirs\n", encoding="utf-8")
    git(["add", "conflict.txt"], path, env)
    commit(path, env, "theirs")

    git(["switch", "-q", "main"], path, env)
    file.write_text("ours\n", encoding="utf-8")
    git(["add", "conflict.txt"], path, env)
    commit(path, env, "ours")


def positive_control(name, directory, config, env):
    control = directory / "control"
    markers = []

    if name == "hooks":
        hooks = directory / "hostile-hooks"
        hooks.mkdir()

        script = hooks / "reference-transaction"
        script.write_text(
            '#!/bin/sh\n'
            ': > "$(dirname "$0")/called"\n'
            'exit 1\n',
            encoding="utf-8",
        )
        script.chmod(0o755)

        marker = hooks / "called"
        set_global(config, "core.hooksPath", hooks, directory, env)

        control.mkdir()

        safe_hooks = directory / "safe-hooks"
        safe_hooks.mkdir()

        git(
            [
                "-c", f"core.hooksPath={safe_hooks}",
                "init", "-q", "-b", "main",
            ],
            control,
            env,
        )

        # A commit updates refs/heads/main on both older and newer Git.
        result = git(
            [
                "-c", "user.name=Codelaxy Probe",
                "-c", "user.email=probe@example.invalid",
                "-c", "commit.gpgsign=false",
                "commit", "--allow-empty", "-qm", "hook probe",
            ],
            control,
            env,
            check=False,
        )

        require(result.returncode != 0, "Hostile hook did not block commit")
        require(marker.exists(), "Hostile hook was not executed")
        markers.append(marker)

    elif name == "template":
        template = directory / "hostile-template"
        (template / "info").mkdir(parents=True)
        (template / "info" / "exclude").write_text(
            "*.txt\n", encoding="utf-8"
        )

        set_global(config, "init.templateDir", template, directory, env)
        init_repo(control, env)

        copied = control / ".git" / "info" / "exclude"
        require(copied.exists(), "Git did not copy hostile template")
        require("*.txt" in copied.read_text(), "Template was not applied")

    elif name == "excludes":
        excludes = directory / "hostile-excludes"
        excludes.write_text("*.txt\n", encoding="utf-8")

        set_global(config, "core.excludesFile", excludes, directory, env)
        init_repo(control, env)

        (control / "probe.txt").write_text("probe\n")
        result = git(["add", "--", "probe.txt"], control, env, check=False)

        require(result.returncode != 0, "Global excludes had no effect")

    elif name == "attributes":
        attributes = directory / "hostile-attributes"
        attributes.write_text(
            "*.txt working-tree-encoding=UTF-16LE\n",
            encoding="utf-8",
        )

        set_global(config, "core.attributesFile", attributes, directory, env)
        init_repo(control, env)

        (control / "probe.txt").write_bytes(b"abc")

        result = git(["add", "--", "probe.txt"], control, env, check=False)
        require(result.returncode != 0, "Hostile attributes had no effect")

        empty = directory / "empty-attributes"
        empty.write_text("")

        git(
            ["-c", f"core.attributesFile={empty}", "add", "--", "probe.txt"],
            control,
            env,
        )

    elif name == "autocrlf":
        set_global(config, "core.autocrlf", "true", directory, env)
        set_global(config, "core.safecrlf", "true", directory, env)

        init_repo(control, env)

        (control / "probe.txt").write_bytes(b"first\nsecond\n")

        poisoned = git(
            ["add", "--", "probe.txt"],
            control,
            env,
            check=False,
        )

        require(
            poisoned.returncode != 0,
            "Hostile autocrlf/safecrlf had no effect",
        )

        git(
            [
                "-c",
                "core.autocrlf=false",
                "add",
                "--",
                "probe.txt",
            ],
            control,
            env,
        )

    elif name in {"merge_ff", "merge_signatures"}:
        key = (
            "merge.ff" if name == "merge_ff"
            else "merge.verifySignatures"
        )
        hostile_value = "only" if name == "merge_ff" else "true"
        safe_value = "true" if name == "merge_ff" else "false"

        set_global(config, key, hostile_value, directory, env)
        create_conflict(control, env)

        result = git(
            ["merge", "--no-edit", "theirs"],
            control,
            env,
            check=False,
        )
        require(
            result.returncode == 128,
            f"{key}: expected exit 128, got {result.returncode}",
        )

        result = git(
            ["-c", f"{key}={safe_value}", "merge", "--no-edit", "theirs"],
            control,
            env,
            check=False,
        )
        require(result.returncode == 1, f"{key}: expected merge conflict")
        require(
            (control / ".git" / "MERGE_HEAD").exists(),
            f"{key}: missing MERGE_HEAD",
        )

    elif name == "branch_merge_options":
        set_global(
            config,
            "branch.main.mergeOptions",
            "-s ours",
            directory,
            env,
        )

        create_conflict(control, env)

        result = git(
            ["merge", "--no-edit", "theirs"],
            control,
            env,
            check=False,
        )

        require(
            result.returncode == 0,
            "Hostile branch mergeOptions did not suppress conflict",
        )
        require(
            not (control / ".git" / "MERGE_HEAD").exists(),
            "Hostile merge unexpectedly left MERGE_HEAD",
        )

    elif name == "ignore_stat":
        set_global(
            config,
            "core.ignoreStat",
            "true",
            directory,
            env,
        )

        init_repo(control, env)

        tracked = control / "tracked.txt"
        tracked.write_text("original\\n", encoding="utf-8")

        git(["add", "--", "tracked.txt"], control, env)
        commit(control, env, "initial")

        flags = git(
            ["ls-files", "-v", "--", "tracked.txt"],
            control,
            env,
        ).stdout

        require(
            flags.startswith("h "),
            "Hostile ignoreStat did not set assume-unchanged",
        )

        tracked.write_text("modified\\n", encoding="utf-8")
        git(["add", "--", "tracked.txt"], control, env)

        staged = git(
            ["diff", "--cached", "--name-only"],
            control,
            env,
        ).stdout

        require(
            not staged.strip(),
            "Hostile ignoreStat did not suppress the change",
        )

    elif name == "fsmonitor":
        script = directory / "monitor.py"
        marker = directory / "monitor.called"

        script.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "with Path(__file__).with_suffix('.called').open('a') as f:\n"
            "    f.write('called\\n')\n"
            "sys.stdout.buffer.write(b'codelaxy-token\\0')\n",
            encoding="utf-8",
        )

        command = (
            f'"{Path(sys.executable).as_posix()}" '
            f'-B "{script.as_posix()}"'
        )

        set_global(config, "core.fsmonitor", command, directory, env)
        init_repo(control, env)

        (control / "tracked.txt").write_text("tracked\n")
        git(["add", "tracked.txt"], control, env)
        commit(control, env, "initial")
        git(["update-index", "--fsmonitor"], control, env)
        git(["status", "--short"], control, env)

        require(marker.exists(), "Global fsmonitor was not executed")
        markers.append(marker)

    return markers


def platform_key():
    if sys.platform == "win32":
        return "windows"

    if sys.platform.startswith("linux"):
        return "linux"

    raise AssertionError(f"Unsupported platform for Golden counts: {sys.platform}")


def read_trx_counts(trx, name):
    """Return outcome counts, cross-checked between TRX counters and results."""
    document = ET.parse(trx)
    counters = document.find(".//{*}Counters")
    require(counters is not None, f"{name}: missing test counters")

    outcomes = [
        result.get("outcome")
        for result in document.findall(".//{*}UnitTestResult")
    ]

    observed = {
        "total": len(outcomes),
        "passed": outcomes.count("Passed"),
        "failed": outcomes.count("Failed"),
        "skipped": outcomes.count("NotExecuted"),
    }

    require(
        sum(observed[key] for key in ("passed", "failed", "skipped"))
        == observed["total"],
        f"{name}: unexpected test outcome in TRX results: {sorted(set(outcomes))}",
    )

    # TRX does not count skipped tests as notExecuted; they are total - executed.
    reported = {key: int(counters.get(key, "-1")) for key in counters.keys()}

    require(
        reported.get("total") == observed["total"]
        and reported.get("passed") == observed["passed"]
        and reported.get("failed") == observed["failed"]
        and reported.get("executed") == observed["total"] - observed["skipped"],
        f"{name}: TRX counters {reported} disagree with results {observed}",
    )

    ignored = {"total", "executed", "passed", "failed"}

    require(
        all(value == 0 for key, value in reported.items() if key not in ignored),
        f"{name}: unexpected non-zero TRX counters: {reported}",
    )

    return observed


def run_golden_tests(name, directory, env):
    results = directory / "results"
    results.mkdir()

    trx = results / f"golden-{name}.trx"

    command = [
        "dotnet", "test", str(PROJECT),
        "--configuration", "Debug",
        "--no-build",
        "--no-restore",
        "--filter", FILTER,
        "--logger", f"trx;LogFileName={trx.name}",
        "--results-directory", str(results),
    ]

    result = subprocess.run(command, cwd=ROOT, env=env)

    require(result.returncode == 0, f"{name}: dotnet test failed")
    require(trx.is_file(), f"{name}: missing TRX report")

    platform = platform_key()
    observed = read_trx_counts(trx, name)
    expected = EXPECTED_COUNTS[platform]

    require(
        observed == expected,
        f"{name}: unexpected test counts on {platform}: "
        f"expected {expected}, observed {observed}",
    )

    print(
        f"{name}: GOLDEN {observed['passed']}/{observed['total']} PASS "
        f"({observed['skipped']} skipped on {platform})",
        flush=True,
    )


def main():
    for name in CASES:
        print(f"\n=== ADVERSARIAL CASE: {name} ===", flush=True)

        with tempfile.TemporaryDirectory(
            prefix=f"codelaxy-{name}-"
        ) as temporary:
            directory = Path(temporary)
            env, config = make_environment(directory)

            markers = positive_control(name, directory, config, env)
            print(f"{name}: POSITIVE CONTROL PASS", flush=True)

            for marker in markers:
                marker.unlink()

            run_golden_tests(name, directory, env)

            for marker in markers:
                require(
                    not marker.exists(),
                    f"{name}: hostile external program was executed",
                )

            print(f"{name}: ISOLATION PASS", flush=True)

    print("\nALL TEN CONFIGURATION CASES: PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nADVERSARIAL FAILURE: {exc}", file=sys.stderr)
        sys.exit(1)
