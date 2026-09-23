"""Run disjoint Unit and source E2E stages, retaining skipped app cases for E2E."""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def app_inventory(module):
    case = getattr(module, "RuntimeAcceptanceTests", None)
    if not isinstance(case, type) or not issubclass(case, unittest.TestCase):
        raise ValueError("RuntimeAcceptanceTests is required in tests/test_app.py.")
    runtime = {item.id() for item in cases(unittest.defaultTestLoader.loadTestsFromTestCase(case))}
    if not runtime:
        raise ValueError("RuntimeAcceptanceTests must contain executable E2E cases.")
    tests = list(cases(unittest.defaultTestLoader.loadTestsFromModule(module)))
    ids = [item.id() for item in tests]
    if len(set(ids)) != len(ids) or not runtime <= set(ids):
        raise ValueError("App test IDs must be unique and include every E2E case.")
    return tests, runtime


def source_digest(root):
    digest = hashlib.sha256()
    paths = [root / "run.py", root / "requirements.txt"]
    for directory in ("app", "modules", "mock_server", "tests", ".github/scripts"):
        paths.extend((root / directory).rglob("*.py"))
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_identity():
    return [str(ROOT), sys.executable, sys.version, sys.platform,
            *[os.environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")]]


class UnitResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed_ids = set()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed_ids.add(test.id())


def run_unit(module, suite, report_path):
    report_path.unlink(missing_ok=True)
    tests, runtime = app_inventory(module)
    app_ids = {test.id() for test in tests}
    discovered = list(cases(suite))
    ids = [test.id() for test in discovered]
    if len(ids) != len(set(ids)) or not app_ids <= set(ids):
        raise ValueError("Unit discovery must contain every app test exactly once.")
    before = source_digest(ROOT)
    selected = [test for test in discovered if test.id() not in runtime]
    result = unittest.TextTestRunner(verbosity=2, resultclass=UnitResult).run(unittest.TestSuite(selected))
    if not result.wasSuccessful():
        return 1
    if source_digest(ROOT) != before:
        raise ValueError("Source changed during Unit tests; rerun Unit before E2E.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "version": 1, "source_digest": before, "run_identity": run_identity(),
        "app_ids": sorted(app_ids), "passed_app_ids": sorted(result.passed_ids & app_ids),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Unit: {len(result.passed_ids & app_ids)} app tests passed; "
          f"{len(app_ids - result.passed_ids)} app tests reserved for E2E.", flush=True)
    return 0


def run_checks(report_path):
    module = importlib.import_module("tests.test_app")
    tests, runtime = app_inventory(module)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    app_ids = {test.id() for test in tests}
    if not isinstance(report, dict) or (
        report.get("version") != 1 or report.get("source_digest") != source_digest(ROOT)
        or report.get("run_identity") != run_identity() or report.get("app_ids") != sorted(app_ids)
    ):
        raise ValueError("Unit results are stale or from another run/source; rerun Unit before E2E.")
    passed = report.get("passed_app_ids")
    if not isinstance(passed, list) or any(not isinstance(item, str) for item in passed):
        raise ValueError("Unit results must list successful app test IDs.")
    if len(set(passed)) != len(passed) or not set(passed) <= app_ids or set(passed) & runtime:
        raise ValueError("Unit results contain invalid or E2E-only test IDs.")
    selected = [test for test in tests if test.id() not in passed]
    print(f"E2E: {len(selected)} app tests; excluding {len(passed)} already passed in Unit.", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    if result.skipped or result.expectedFailures:
        print("E2E tests cannot be skipped or marked expected-failure before packaging.", file=sys.stderr)
        return 2
    if source_digest(ROOT) != report["source_digest"]:
        raise ValueError("Source changed during E2E; rerun Unit and E2E.")
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("unit", "e2e"), default="e2e")
    parser.add_argument("--unit-results", type=Path, default=ROOT / ".test-results/unit.json")
    args = parser.parse_args(argv)
    os.environ["JUDICIAL_RUNTIME_CHECKS"] = "0" if args.phase == "unit" else "1"
    try:
        if args.phase == "unit":
            # Discover with a stable package prefix so both stages use identical IDs.
            module = importlib.import_module("tests.test_app")
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
            return run_unit(module, suite, args.unit_results)
        return run_checks(args.unit_results)
    except (OSError, ValueError) as exc:
        print(f"{args.phase} stage blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
