"""RoadmapRegistry test reporter. Python stdlib only."""

import argparse
import hashlib
import json
import os
import sys
import time
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "tools" / "registry"


def source_snapshot():
    files = {}

    for directory in ("tools/registry", "docs/registry"):
        for path in sorted((REPO / directory).rglob("*")):
            if path.is_symlink():
                raise RuntimeError(f"Symlink in source snapshot: {path}")
            if path.is_file():
                name = path.relative_to(REPO).as_posix()
                files[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    for relative in (
        "tools/ci/registry_gate.py",
        "tools/ci/registry-portable-skips.json",
    ):
        path = REPO / relative

        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Missing or unsafe gate control: {relative}")

        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()

    encoded = json.dumps(
        files, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest(), len(files)


class DetailedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = {}
        self.outcomes = {}
        self.records = []

    def startTest(self, test):
        self.started[id(test)] = time.perf_counter()
        self.outcomes[id(test)] = ("PASS", "")
        super().startTest(test)

    def addSkip(self, test, reason):
        self.outcomes[id(test)] = ("SKIP", reason)
        super().addSkip(test, reason)

    def addFailure(self, test, err):
        self.outcomes[id(test)] = ("FAIL", self._exc_info_to_string(err, test))
        super().addFailure(test, err)

    def addError(self, test, err):
        self.outcomes[id(test)] = ("ERROR", self._exc_info_to_string(err, test))
        super().addError(test, err)

    def addExpectedFailure(self, test, err):
        self.outcomes[id(test)] = ("XFAIL", "")
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.outcomes[id(test)] = ("XPASS", "")
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            kind = "FAIL" if issubclass(err[0], AssertionError) else "ERROR"
            self.outcomes[id(test)] = (kind, str(subtest))
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        status, reason = self.outcomes.pop(id(test), ("UNKNOWN", ""))
        elapsed = time.perf_counter() - self.started.pop(
            id(test), time.perf_counter()
        )

        parts = test.id().split(".")
        module = ".".join(parts[:-2]) if len(parts) >= 3 else "unknown"

        self.records.append({
            "id": test.id(),
            "module": module,
            "status": status,
            "reason": reason,
            "seconds": round(elapsed, 4),
        })
        super().stopTest(test)



def check_skip_policy(records, policy_path):
    data = json.loads(policy_path.read_text(encoding="utf-8"))

    if data.get("schema") != "clx.registry-skip-policy/1":
        raise ValueError("Unsupported policy schema")

    if data.get("profile") != "portable":
        raise ValueError("Unexpected policy profile")

    expected = {}

    for group in data["groups"]:
        prefix = group["class"]
        reason = group["reason_contains"]

        if not isinstance(reason, str) or not reason:
            raise ValueError("Missing required skip reason")

        for method in group["tests"]:
            test_id = f"{prefix}.{method}"

            if test_id in expected:
                raise ValueError(f"Duplicate policy ID: {test_id}")

            expected[test_id] = reason

    if len(expected) != data["allowed_skips"]:
        raise ValueError("Policy count mismatch")

    skipped = [r for r in records if r["status"] == "SKIP"]
    actual_ids = [r["id"] for r in skipped]
    errors = []

    if len(actual_ids) != len(set(actual_ids)):
        errors.append("Duplicate skipped test ID")

    for record in skipped:
        test_id = record["id"]

        if test_id not in expected:
            errors.append(f"Unexpected SKIP: {test_id}")
        elif expected[test_id] not in record["reason"]:
            errors.append(f"Wrong SKIP reason: {test_id}")

    for test_id in sorted(set(expected) - set(actual_ids)):
        errors.append(f"Expected SKIP missing: {test_id}")

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-tests", type=int, default=852)
    parser.add_argument("--expected-skips", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--skip-policy", type=Path)
    args = parser.parse_args()

    if args.expected_tests < 1 or args.expected_skips < 0:
        parser.error("Invalid expected test or SKIP count")

    if args.expected_skips > 0 and args.skip_policy is None:
        parser.error("Expected SKIPs require an explicit skip policy")

    if args.skip_policy is not None:
        args.skip_policy = args.skip_policy.resolve()

        try:
            specification = json.loads(
                args.skip_policy.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            parser.error(f"Cannot load skip policy: {exc}")

        if not isinstance(specification, dict) or (
            specification.get("schema") != "clx.registry-skip-policy/1"
            or specification.get("profile") != "portable"
            or specification.get("expected_tests") != args.expected_tests
            or specification.get("allowed_skips") != args.expected_skips
        ):
            parser.error("Skip policy and CLI expectations disagree")

    before, file_count = source_snapshot()

    os.chdir(REGISTRY)
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(REGISTRY / "tests"),
        top_level_dir=str(REGISTRY),
    )

    runner = unittest.TextTestRunner(
        stream=sys.stderr,
        verbosity=2 if args.verbose else 1,
        resultclass=DetailedResult,
    )

    print("\n=== ROADMAP REGISTRY TEST GATE ===", flush=True)
    result = runner.run(suite)

    after, _ = source_snapshot()
    counts = Counter(r["status"] for r in result.records)

    policy_errors = []
    if args.skip_policy is not None:
        try:
            policy_errors = check_skip_policy(
                result.records, args.skip_policy
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            policy_errors = [f"Invalid skip policy: {exc}"]

    modules = defaultdict(list)
    for record in result.records:
        modules[record["module"]].append(record)

    print("\n=== TEST MODULES ===")
    for name, records in sorted(modules.items()):
        c = Counter(r["status"] for r in records)
        elapsed = sum(r["seconds"] for r in records)
        print(
            f"{name:32} PASS={c['PASS']:3} "
            f"SKIP={c['SKIP']:2} "
            f"FAIL={c['FAIL']:2} "
            f"ERROR={c['ERROR']:2} "
            f"{elapsed:7.2f}s"
        )

    print("\n=== SKIPPED TESTS ===")
    skipped = [r for r in result.records if r["status"] == "SKIP"]

    if not skipped:
        print("None")
    else:
        for record in skipped:
            print(f"{record['id']}: {record['reason']}")

    print("\n=== SLOWEST TESTS ===")
    for record in sorted(
        result.records, key=lambda r: r["seconds"], reverse=True
    )[:10]:
        print(f"{record['seconds']:7.3f}s  {record['id']}")

    passed = (
        result.wasSuccessful()
        and result.testsRun == args.expected_tests
        and counts["SKIP"] == args.expected_skips
        and counts["PASS"] + counts["SKIP"] == result.testsRun
        and len(result.records) == result.testsRun
        and len({r["id"] for r in result.records}) == result.testsRun
        and before == after
        and not policy_errors
    )

    report = {
        "schema": "clx.registry-test-report/1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "tests_run": result.testsRun,
        "expected_tests": args.expected_tests,
        "expected_skips": args.expected_skips,
        "counts": dict(counts),
        "source_files": file_count,
        "source_fingerprint_before": before,
        "source_fingerprint_after": after,
        "source_unchanged": before == after,
        "gate_passed": passed,
        "skip_policy": args.skip_policy.name if args.skip_policy else None,
        "skip_policy_errors": policy_errors,
        "tests": result.records,
    }

    output = REPO / "artifacts" / "registry-reports"
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"registry-{time.time_ns()}.json"

    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("\n=== FINAL VERDICT ===")
    print(
        f"PASS={counts['PASS']} SKIP={counts['SKIP']} "
        f"FAIL={counts['FAIL']} ERROR={counts['ERROR']}"
    )
    print(f"Source unchanged: {before == after}")
    print(f"Expected: {args.expected_tests} tests, {args.expected_skips} skips")
    print(f"JSON report: {path}")
    for error in policy_errors:
        print(f"SKIP POLICY ERROR: {error}")

    print("GATE:", "PASS" if passed else "FAIL")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(
                f"## RoadmapRegistry: {'PASS' if passed else 'FAIL'}\n\n"
                f"Tests: {result.testsRun}, PASS: {counts['PASS']}, "
                f"SKIP: {counts['SKIP']}, FAIL: {counts['FAIL']}, "
                f"ERROR: {counts['ERROR']}\n\n"
                f"Source unchanged: {before == after}\n"
            )

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
