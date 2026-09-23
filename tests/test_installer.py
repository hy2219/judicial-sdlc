import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))

import build_installer

SHA = "a" * 40


def approval(commit=SHA, repo="example/template", plan="plans/1.json", issue=1):
    return {
        "repository": repo, "issue": issue, "plan_path": plan,
        "plan_blob_sha": "b" * 40, "base_sha": "d" * 40,
        "plan_approval": "manual_pr_comment_not_machine_verified",
        "pull_request": 3, "implementation_head_sha": "e" * 40,
        "head_sha": commit, "source_commit": commit,
        "implementation_merged_by": "implementation-maintainer",
        "merged_to_default_branch": True, "merge_method": "squash",
        "changed_files": ["app/gui.py"],
    }


class InstallerTests(unittest.TestCase):
    def test_identity_is_stable_per_source_and_distinct_across_tasks(self):
        first = build_installer.installer_identity(approval(), SHA, "demo-1")
        self.assertEqual(first, build_installer.installer_identity(approval(), SHA, "demo-1"))
        next_version = build_installer.installer_identity(approval(), SHA, "demo-2")
        self.assertEqual(first["product_id"], next_version["product_id"])
        for record, sha in [(approval(repo="other/template"), SHA),
                            (approval(plan="plans/2.json", issue=2), SHA),
                            (approval(commit="b" * 40), "b" * 40)]:
            new = build_installer.installer_identity(record, sha, "demo-1")
            self.assertNotEqual(first["product_id"], new["product_id"])
            self.assertNotEqual(first["product_slug"], new["product_slug"])
        self.assertTrue(first["requires_admin"])
        self.assertTrue(first["install_directory"].startswith("%ProgramFiles%\\"))
        self.assertFalse(first["application_auto_run"])
        self.assertFalse(first["runtime_payload_self_extraction"])
        self.assertFalse(first["policy_changes"])

    def test_invalid_identity_or_approval_is_rejected(self):
        for record, sha, version in [
            (approval(), "main", "demo-1"),
            (approval(), SHA, 'bad"\nversion'),
            ({**approval(), "head_sha": "b" * 40}, SHA, "demo-1"),
            ({**approval(), "source_commit": "b" * 40}, SHA, "demo-1"),
            ({**approval(), "merged_to_default_branch": False}, SHA, "demo-1"),
            ({**approval(), "merged_to_default_branch": 1}, SHA, "demo-1"),
            ({**approval(), "merge_method": "merge"}, SHA, "demo-1"),
            ({**approval(), "merge_method": "rebase"}, SHA, "demo-1"),
            ({**approval(), "issue": 2}, SHA, "demo-1"),
            ({**approval(), "plan_approval": "verified"}, SHA, "demo-1"),
            ({**approval(), "plan_pull_request": 2}, SHA, "demo-1"),
            (approval(repo="example/../../unsafe"), SHA, "demo-1"),
            (approval(plan="../elsewhere.json"), SHA, "demo-1"),
            (None, SHA, "demo-1"),
        ]:
            with self.subTest(record=record), self.assertRaises(ValueError):
                build_installer.installer_identity(record, sha, version)

    def test_complete_merge_provenance_is_required_without_extra_reviews(self):
        self.assertEqual(build_installer.validate_source_approval(approval(), SHA), approval())
        for field in approval():
            record = approval()
            del record[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                build_installer.installer_identity(record, SHA, "demo-1")
        for field in ("issue", "pull_request"):
            for value in (0, -1, True, False, 1.5, "3", None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_installer.installer_identity({**approval(), field: value}, SHA, "demo-1")
        for field in ("plan_blob_sha", "base_sha", "implementation_head_sha"):
            for value in ("main", "a" * 39, "g" * 40, 1, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_installer.installer_identity({**approval(), field: value}, SHA, "demo-1")
        for field in ("implementation_merged_by",):
            for value in ("", " ", "user\n", "two users", "agent[bot]", 1, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_installer.installer_identity({**approval(), field: value}, SHA, "demo-1")
            build_installer.installer_identity({**approval(), field: "person_name.enterprise"}, SHA, "demo-1")
        for files in (None, [], "app/gui.py", [None], [""], ["../app.py"], ["/app.py"], ["a\nb"]):
            with self.subTest(files=files), self.assertRaises(ValueError):
                build_installer.installer_identity({**approval(), "changed_files": files}, SHA, "demo-1")

    def test_legacy_unmerged_review_report_is_rejected(self):
        record = {
            "repository": "example/template", "plan_path": "plans/1.json", "head_sha": SHA,
            "merged_to_default_branch": False,
            "plan_approval_review_ids": [1], "implementation_approval_review_ids": [2],
        }
        with self.assertRaises(ValueError):
            build_installer.installer_identity(record, SHA, "demo-1")

    def test_onedir_payload_inventory_and_required_models(self):
        with tempfile.TemporaryDirectory(prefix=".delivery-test-", dir=ROOT) as directory:
            root = Path(directory)
            payload = root / "workflow-app"
            contents = {
                "workflow-app.exe": b"not executable",
                "_internal/python312.dll": b"not a library",
                "_internal/assets/klocr/manifest.json": b"{}",
                "_internal/THIRD-PARTY-NOTICES.txt": b"synthetic-notices",
                "_internal/assets/klocr/model.pth": b"synthetic-weight",
            }
            for name, data in contents.items():
                path = payload / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            notices = root / "THIRD-PARTY-NOTICES.txt"
            notices.write_bytes(b"synthetic-notices")
            models = [{"filename": "model.pth", "sha256": hashlib.sha256(b"synthetic-weight").hexdigest()}]
            with patch.object(build_installer, "MODELS", models):
                files = build_installer.payload_files(payload, notices)
                self.assertEqual(set(files), set(contents))
                self.assertNotIn(str(root), json.dumps(files))
                (payload / "_internal/assets/klocr/model.pth").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "model"):
                    build_installer.payload_files(payload, notices)

    def test_missing_payload_and_unexpected_root_fail(self):
        with tempfile.TemporaryDirectory(prefix=".delivery-test-", dir=ROOT) as directory:
            root = Path(directory)
            notices = root / "notice.txt"
            notices.write_text("synthetic", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_installer.payload_files(root, notices)
            with self.assertRaises(FileNotFoundError):
                build_installer.payload_files(root / "missing", notices)

    def test_compiler_is_called_with_args_not_a_shell_or_installer(self):
        identity = build_installer.installer_identity(approval(), SHA, "demo-1")
        args = build_installer.compiler_arguments("ISCC.exe", identity, "payload", "dist", "notice", "manifest")
        self.assertEqual(args[0], "ISCC.exe")
        self.assertTrue(args[-1].endswith("windows-installer.iss"))
        self.assertIn("/DProductId=" + identity["product_id"], args)
        self.assertNotIn("workflow-setup.exe", args)
        with self.assertRaises(ValueError):
            build_installer.compiler_arguments("ISCC.exe", {**identity, "version": 'bad"\n'}, "p", "d", "n", "m")

    def test_installer_template_never_runs_app_or_changes_policy(self):
        text = (ROOT / "packaging/windows-installer.iss").read_text(encoding="utf-8")
        self.assertIn("AppName=Judicial Workflow ({#ProductSlug})", text)
        self.assertIn("OutputBaseFilename=workflow-setup", text)
        self.assertIn(r'Filename: "{app}\workflow-app.exe"', text)
        self.assertNotIn("citation", text.lower())
        self.assertIn("PrivilegesRequired=admin", text)
        self.assertIn(r"DefaultDirName={commonpf}\Judicial-SDLC\{#ProductSlug}", text)
        self.assertIn('DestDir: "{app}\\_internal"', text)
        self.assertIn("Uninstallable=yes", text)
        self.assertIn("[Icons]", text)
        for forbidden in (
            "[Run]", "[UninstallRun]", "[InstallDelete]", "[UninstallDelete]",
            "[Registry]", "[Code]", "ExecutionPolicy", "Set-MpPreference", "{sys}",
            "PrivilegesRequiredOverridesAllowed", "Permissions:", "Tesseract-OCR",
        ):
            self.assertNotIn(forbidden, text)

    def test_compiler_main_refuses_non_windows(self):
        with patch.object(build_installer.sys, "platform", "darwin"), patch.object(
            build_installer.subprocess, "run"
        ) as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build_installer.main([
                "--version", "demo-1", "--commit", SHA, "--approval", "not-read.json",
            ]), 2)
        run.assert_not_called()

    def test_compiler_main_records_complete_gate_provenance_without_execution(self):
        with tempfile.TemporaryDirectory(prefix=".delivery-test-", dir=ROOT) as directory:
            root = Path(directory)
            output = root / "dist"
            output.mkdir()
            record = approval()
            approval_path = root / "approval.json"
            approval_path.write_text(json.dumps(record), encoding="utf-8")

            def fake_compile(args, **kwargs):
                self.assertEqual(args[0], "ISCC.exe")
                self.assertEqual(kwargs, {"check": True})
                (output / "workflow-setup.exe").write_bytes(b"synthetic installer, not executable")

            with patch.object(build_installer, "ROOT", root), patch.object(
                build_installer.sys, "platform", "win32"
            ), patch.object(build_installer, "payload_files", return_value={}), patch.object(
                build_installer, "compiler_path", return_value=Path("ISCC.exe")
            ), patch.object(build_installer.subprocess, "run", side_effect=fake_compile) as run:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(build_installer.main([
                        "--version", "demo-1", "--commit", SHA, "--approval", str(approval_path),
                    ]), 0)
            run.assert_called_once()
            build = json.loads((output / "installer-build.json").read_text(encoding="utf-8"))
            self.assertEqual(build["source_approval"], record)
            self.assertEqual(build["source_commit"], SHA)
            self.assertFalse(build["installer_executed"])
            self.assertFalse(build["application_executed"])
            self.assertEqual(build["payload_manifest_sha256"],
                             build_installer.file_hash(output / "payload-manifest.json"))

    def test_gui_suggests_user_documents_not_install_folder(self):
        try:
            from app.gui import user_document_directory
        except ImportError:
            self.skipTest("Tkinter is unavailable in this source-test environment")
        with tempfile.TemporaryDirectory(prefix=".delivery-test-", dir=ROOT) as directory:
            home = Path(directory)
            with patch("app.gui.Path.home", return_value=home):
                self.assertEqual(user_document_directory(), str(home))
                (home / "Documents").mkdir()
                self.assertEqual(user_document_directory(), str(home / "Documents"))


if __name__ == "__main__":
    unittest.main()
