import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
import runtime_check


class RuntimeCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.report = Path(self.directory.name) / "unit.json"
        for name, value in (("source_digest", "synthetic-digest"), ("run_identity", ["synthetic-run"])):
            mock = patch.object(runtime_check, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        for redirect in (contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO())):
            self.enterContext(redirect)

    def unit(self, module):
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        return runtime_check.run_unit(module, suite, self.report)

    def e2e(self, module):
        with patch.object(runtime_check.importlib, "import_module", return_value=module):
            return runtime_check.run_checks(self.report)

    def module(self, *, skip_elsewhere=False, fail_unit=False, fail_e2e=False, skip_e2e=False):
        calls = []

        class Unit(unittest.TestCase):
            def test_unit(self):
                calls.append("unit")
                if fail_unit:
                    self.fail("Unit failed")

        class Runtime(unittest.TestCase):
            def test_e2e(self):
                calls.append("e2e")
                if skip_e2e:
                    self.skipTest("Still unavailable")
                if fail_e2e:
                    self.fail("E2E failed")

        class Elsewhere(unittest.TestCase):
            def test_dependency(self):
                if skip_elsewhere:
                    self.skipTest("Needs runtime dependencies")
                calls.append("elsewhere")

        return SimpleNamespace(RuntimeAcceptanceTests=Runtime, UnitTests=Unit, OtherTests=Elsewhere), calls

    def test_unit_successes_do_not_run_twice_and_all_app_cases_are_covered(self):
        module, calls = self.module()
        self.assertEqual(self.unit(module), 0)
        self.assertEqual(calls, ["elsewhere", "unit"])
        self.assertEqual(self.e2e(module), 0)
        self.assertEqual(calls, ["elsewhere", "unit", "e2e"])
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(len(report["app_ids"]), 3)
        self.assertEqual(len(report["passed_app_ids"]), 2)

    def test_skipped_case_in_another_class_is_run_in_e2e(self):
        module, calls = self.module(skip_elsewhere=True)
        self.assertEqual(self.unit(module), 0)
        self.assertEqual(calls, ["unit"])
        module.OtherTests.__unittest_skip__ = False
        # Simulate a fresh import where the runtime dependency becomes available.
        def available(case):
            calls.append("elsewhere")
        module.OtherTests.test_dependency = available
        self.assertEqual(self.e2e(module), 0)
        self.assertCountEqual(calls, ["unit", "elsewhere", "e2e"])

    def test_permanent_skip_anywhere_in_e2e_blocks_packaging(self):
        module, _ = self.module(skip_elsewhere=True)
        self.assertEqual(self.unit(module), 0)
        self.assertEqual(self.e2e(module), 2)
        module, _ = self.module(skip_e2e=True)
        self.assertEqual(self.unit(module), 0)
        self.assertEqual(self.e2e(module), 2)

    def test_failures_are_not_cached_as_passes(self):
        module, _ = self.module()
        self.assertEqual(self.unit(module), 0)
        module, _ = self.module(fail_unit=True)
        self.assertEqual(self.unit(module), 1)
        self.assertFalse(self.report.exists())
        module, _ = self.module(fail_e2e=True)
        self.assertEqual(self.unit(module), 0)
        self.assertEqual(self.e2e(module), 1)

    def test_failed_unit_subtest_does_not_produce_a_success_record(self):
        module, _ = self.module()
        def failed_subtest(case):
            with case.subTest(item=1):
                case.fail("Failed inside subTest")
        module.UnitTests.test_unit = failed_subtest
        self.assertEqual(self.unit(module), 1)
        self.assertFalse(self.report.exists())

    def test_expected_failure_in_e2e_is_not_acceptance(self):
        module, _ = self.module(fail_e2e=True)
        module.RuntimeAcceptanceTests.test_e2e = unittest.expectedFailure(
            module.RuntimeAcceptanceTests.test_e2e,
        )
        self.assertEqual(self.unit(module), 0)
        self.assertEqual(self.e2e(module), 2)

    def test_missing_empty_or_duplicate_runtime_inventory_blocks(self):
        for module in (SimpleNamespace(), SimpleNamespace(RuntimeAcceptanceTests=object),
                       SimpleNamespace(RuntimeAcceptanceTests=type("Empty", (unittest.TestCase,), {}))):
            with self.assertRaises(ValueError):
                self.unit(module)
        module, _ = self.module()
        module.Alias = module.RuntimeAcceptanceTests
        with self.assertRaisesRegex(ValueError, "unique"):
            self.unit(module)

    def test_missing_or_stale_reports_cannot_omit_cases(self):
        module, _ = self.module()
        with self.assertRaises(FileNotFoundError):
            self.e2e(module)
        for field, value in (("version", 2), ("source_digest", "changed"),
                             ("run_identity", ["another-job"]), ("app_ids", []),
                             ("passed_app_ids", ["invented"]), ("passed_app_ids", [None]),
                             ("passed_app_ids", None)):
            self.assertEqual(self.unit(module), 0)
            report = json.loads(self.report.read_text(encoding="utf-8"))
            report[field] = value
            self.report.write_text(json.dumps(report), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.e2e(module)
        self.report.write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.e2e(module)

    def test_unit_cannot_claim_runtime_pass_or_duplicate_ids(self):
        module, _ = self.module()
        for bad_ids in (
            [module.RuntimeAcceptanceTests("test_e2e").id()],
            [module.UnitTests("test_unit").id()] * 2,
        ):
            self.unit(module)
            report = json.loads(self.report.read_text(encoding="utf-8"))
            report["passed_app_ids"] = bad_ids
            self.report.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.e2e(module)

    def test_source_mutation_during_unit_blocks_report(self):
        module, _ = self.module()
        with patch.object(runtime_check, "source_digest", side_effect=["before", "after"]):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                self.unit(module)
        self.assertFalse(self.report.exists())

    def test_incomplete_discovery_is_not_success(self):
        module, _ = self.module()
        with self.assertRaisesRegex(ValueError, "every app test"):
            runtime_check.run_unit(
                module, unittest.TestSuite([module.UnitTests("test_unit")]), self.report,
            )

    def test_cli_sets_environment_before_test_import_and_reports_missing_unit(self):
        module, _ = self.module()
        with patch.object(runtime_check.importlib, "import_module", return_value=module), \
                patch.dict(runtime_check.os.environ, {"JUDICIAL_RUNTIME_CHECKS": "0"}):
            self.assertEqual(runtime_check.main(["--unit-results", str(self.report)]), 2)
            self.assertEqual(runtime_check.os.environ["JUDICIAL_RUNTIME_CHECKS"], "1")

    def test_fresh_process_stages_run_every_test_once_including_misplaced_gate(self):
        root = Path(self.directory.name) / "fixture"
        (root / "tests").mkdir(parents=True)
        (root / ".github/scripts").mkdir(parents=True)
        script = root / ".github/scripts/runtime_check.py"
        script.write_bytes(Path(runtime_check.__file__).read_bytes())
        (root / "run.py").write_text("", encoding="utf-8")
        (root / "requirements.txt").write_text("", encoding="utf-8")
        (root / "tests/__init__.py").write_text("", encoding="utf-8")
        (root / "tests/test_app.py").write_text(
            'import os,unittest\nfrom pathlib import Path\n'
            'def note(value):\n'
            '    with Path("calls.txt").open("a",encoding="utf-8") as f: f.write(value+"\\n")\n'
            'class UnitTests(unittest.TestCase):\n'
            '    def test_fast(self): note("unit")\n'
            '    @unittest.skipUnless(os.environ.get("JUDICIAL_RUNTIME_CHECKS")=="1","runtime")\n'
            '    def test_misplaced(self): note("misplaced")\n'
            '@unittest.skipUnless(os.environ.get("JUDICIAL_RUNTIME_CHECKS")=="1","runtime")\n'
            'class RuntimeAcceptanceTests(unittest.TestCase):\n'
            '    def test_flow(self): note("e2e")\n', encoding="utf-8",
        )
        for phase in ("unit", "e2e"):
            subprocess.run([sys.executable, str(script), "--phase", phase],
                           cwd=root, check=True, capture_output=True, text=True)
        self.assertEqual(sorted((root / "calls.txt").read_text(encoding="utf-8").splitlines()),
                         ["e2e", "misplaced", "unit"])
        with (root / "tests/test_app.py").open("a", encoding="utf-8") as output:
            output.write("\n# Changed source invalidates earlier Unit results.\n")
        result = subprocess.run([sys.executable, str(script), "--phase", "e2e"],
                                cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("stale", result.stderr)
