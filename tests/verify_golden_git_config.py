
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
    "fsmonitor",
)


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
        result = git(["init", "-q", "-b", "main"], control, env, check=False)

        require(result.returncode != 0, "Hostile hook did not block init")
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

    counters = ET.parse(trx).find(".//{*}Counters")
    require(counters is not None, f"{name}: missing test counters")

    total = int(counters.get("total", "-1"))
    passed = int(counters.get("passed", "-1"))
    failed = int(counters.get("failed", "-1"))

    require(
        (total, passed, failed) == (6, 6, 0),
        f"{name}: unexpected test counts: "
        f"total={total}, passed={passed}, failed={failed}",
    )

    print(f"{name}: GOLDEN 6/6 PASS", flush=True)


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

    print("\nALL EIGHT CONFIGURATION CASES: PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nADVERSARIAL FAILURE: {exc}", file=sys.stderr)
        sys.exit(1)
