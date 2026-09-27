import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / ".github/scripts"))

import check_public_content
import freeze_windows
import package_metadata


class ProjectWorkspace(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix=".delivery-test-", dir=ROOT)
        self.addCleanup(self.workspace.cleanup)
        self.directory = Path(self.workspace.name)


class PublicContentTests(ProjectWorkspace):
    def setUp(self):
        super().setUp()
        self.git("init", "--quiet")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.directory), *args],
            check=True, capture_output=True,
        )

    def stage(self, name, data=b"synthetic-only\n"):
        target = self.directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.git("add", "--", name)
        return target

    def test_first_commit_not_required(self):
        self.stage("demo.py", b'token_name = "synthetic-only"\n')
        self.assertEqual(check_public_content.audit(self.directory), [])

    def test_empty_index_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "No tracked/index files"):
            check_public_content.audit(self.directory)

    def test_no_git_fails_closed(self):
        not_git = self.directory / "child"
        not_git.mkdir()
        with self.assertRaisesRegex(RuntimeError, "own Git repository root"):
            check_public_content.audit(not_git)

    def test_git_unavailable_returns_explicit_failure(self):
        errors = io.StringIO()
        with mock.patch.object(
            check_public_content.subprocess, "run", side_effect=FileNotFoundError("Git unavailable")
        ), contextlib.redirect_stderr(errors):
            self.assertEqual(check_public_content.main(["--root", str(self.directory)]), 2)
        self.assertIn("Preflight error", errors.getvalue())

    def test_default_preflight_root_survives_github_script_relocation(self):
        with mock.patch.object(check_public_content, "audit", return_value=[]) as audit:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_public_content.main([]), 0)
        audit.assert_called_once_with(ROOT)

    def test_staged_pdf_rejected_after_worktree_replaced(self):
        target = self.stage("innocent.txt", b"%" + b"PDF-1.4\nsynthetic\n")
        target.write_text("safe replacement\n", encoding="utf-8")
        self.assertTrue(any("PDF content" in reason for _, reason in check_public_content.audit(self.directory)))

    def test_staged_secret_rejected_after_worktree_removed(self):
        secret = "ghp_" + "a" * 36
        target = self.stage("demo.txt", secret.encode())
        target.unlink()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = check_public_content.main(["--root", str(self.directory)])
        self.assertEqual(result, 1)
        self.assertIn("demo.txt", output.getvalue())
        self.assertNotIn(secret, output.getvalue())

    def test_unstaged_change_is_checked(self):
        target = self.stage("demo.txt")
        target.write_bytes(b"\x00synthetic binary")
        self.assertTrue(any("binary" in reason for _, reason in check_public_content.audit(self.directory)))

    def test_untracked_files_are_not_audited(self):
        self.stage("demo.py")
        (self.directory / "not-tracked.pdf").write_bytes(b"%" + b"PDF-1.4")
        self.assertEqual(check_public_content.audit(self.directory), [])

    def test_prohibited_paths(self):
        for name in (
            "sample.pdf", "picture.PNG", "nested/report.docx", "inputs/demo.txt",
            "output/result.txt", "local/demo.txt", ".env", ".env.example",
            "credentials.json", "id_ed25519", "bundle.zip", ".aws/config",
        ):
            with self.subTest(name=name):
                self.assertTrue(check_public_content.path_reasons(name))

    def test_private_urls_and_key_patterns(self):
        fixtures = [
            ("https://" + "tenant.sharepoint.com/sites/synthetic").encode(),
            ("http://" + "10.2.3.4/synthetic").encode(),
            ("https://" + "service.internal/test").encode(),
            ("https://" + "fake:synthetic@example.invalid").encode(),
            ("-----BEGIN " + "PRIVATE KEY-----").encode(),
            b'password = "fake-fixture-value"\n',
        ]
        for fixture in fixtures:
            with self.subTest(index=fixtures.index(fixture)):
                self.assertTrue(check_public_content.content_reasons(fixture))

    def test_loopback_and_placeholder_allowed(self):
        self.assertEqual(
            check_public_content.content_reasons(
                b'http://127.0.0.1:1234/test\npassword = "synthetic-only"\n'
            ),
            set(),
        )

    @unittest.skipIf(os.name == "nt", "Symlink creation needs Windows privileges")
    def test_symlink_rejected_without_reading_target(self):
        self.stage("safe.txt")
        (self.directory / "link.txt").symlink_to("safe.txt")
        self.git("add", "--", "link.txt")
        self.assertTrue(any("symlink" in reason for _, reason in check_public_content.audit(self.directory)))

    def test_project_source_passes_same_content_rules(self):
        paths = [
            ROOT / "README.md",
            *sorted((ROOT / "docs").glob("*.rst")),
            *sorted((ROOT / "packaging").glob("*.py")),
            *sorted((ROOT / ".github/scripts").glob("*.py")),
            ROOT / "tests/test_delivery.py",
        ]
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(check_public_content.content_reasons(path.read_bytes()), set())


class MetadataTests(ProjectWorkspace):
    def setUp(self):
        super().setUp()
        self.approval_record = {
            "repository": "example/demo", "issue": 1, "plan_path": "plans/1.json",
            "plan_blob_sha": "b" * 40, "base_sha": "d" * 40,
            "plan_approval": "manual_pr_comment_not_machine_verified",
            "pull_request": 3, "implementation_head_sha": "e" * 40,
            "head_sha": "a" * 40, "source_commit": "a" * 40,
            "implementation_merged_by": "implementation-maintainer",
            "merged_to_default_branch": True, "merge_method": "squash",
            "changed_files": ["app/gui.py"],
        }
        self.approval = self.directory / "approval.json"
        self.approval.write_text(json.dumps(self.approval_record), encoding="utf-8")

    def make_notices(self, executable):
        notices = executable.with_name("THIRD-PARTY-NOTICES.txt")
        notices.write_text("Synthetic license fixture, not a license grant.\n", encoding="utf-8")
        self.make_build_record(executable)
        return notices

    def make_build_record(self, executable, version="demo-1"):
        manifest = executable.with_name("payload-manifest.json")
        manifest.write_text(json.dumps({"source_commit": "a" * 40, "files": {}}), encoding="utf-8")
        record = {
            "source_commit": "a" * 40, "version": version,
            "source_approval": self.approval_record,
            "installer_sha256": package_metadata.file_hash(executable),
            "payload_manifest_sha256": package_metadata.file_hash(manifest),
            "payload_format": "pyinstaller_onedir", "installer_format": "inno_setup",
            "installer_executed": False, "application_executed": False,
            "application_auto_run": False, "policy_changes": False,
            "install_directory": "%ProgramFiles%\\Judicial-SDLC\\synthetic",
            "product_id": "synthetic", "repository": "example/demo", "plan_path": "plans/1.json",
        }
        executable.with_name("installer-build.json").write_text(json.dumps(record), encoding="utf-8")

    def test_checksum_and_explicit_limitations(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic executable fixture, not a real binary")
        model_hashes = {"synthetic-detector.pth": "b" * 64, "synthetic-recognizer.pth": "c" * 64}
        self.make_notices(executable)
        with mock.patch.object(package_metadata, "validate_models", return_value=model_hashes) as validate:
            metadata_path, checksum_path = package_metadata.write_metadata(
                executable, "demo-1", "a" * 40, self.approval
            )
        validate.assert_called_once_with()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        self.assertEqual(metadata["schema_version"], 10)
        self.assertEqual(metadata["filename"], "workflow-setup.exe")
        self.assertEqual(metadata["version"], "demo-1")
        self.assertEqual(metadata["source_commit"], "a" * 40)
        self.assertEqual(metadata["source_approval"], self.approval_record)
        self.assertEqual(metadata["sha256"], digest)
        self.assertEqual(metadata["mode"], "mock-only")
        self.assertFalse(metadata["synthetic_documents_only"])
        self.assertEqual(metadata["document_processing"], "local_only")
        self.assertFalse(metadata["console_window"])
        self.assertEqual(metadata["diagnostics"], "local_error_types_and_code_locations_only")
        self.assertIs(metadata["built_executable_executed"], False)
        self.assertEqual(metadata["static_analysis"], "not_run")
        self.assertFalse(metadata["runtime_behavior_verified"])
        self.assertEqual(metadata["ocr"], {
            "engine": "KLOCR",
            "version": package_metadata.KLOCR_REVISION,
            "languages": ["ko", "en"],
            "device": "cpu",
            "gpu": False,
            "runtime_downloads": False,
            "detector": "CRAFT",
            "recognizer": "JHL3/KLOCR",
            "confidence_kind": package_metadata.CONFIDENCE_KIND,
            "weights_license": "CC-BY-NC-SA-4.0",
            "license_review_required": True,
            "model_sha256": model_hashes,
            "model_hash_scope": "verified_build_inputs_and_staged_payload_not_installed_runtime",
        })
        self.assertEqual(metadata["packaging"]["type"], "fixed_folder_installer")
        self.assertFalse(metadata["installer_executed"])
        self.assertFalse(metadata["application_executed"])
        self.assertFalse(metadata["packaging"]["policy_changes"])
        self.assertEqual(metadata["antivirus_scan"], "not_implemented")
        self.assertEqual(metadata["dynamic_sandbox"], "not_implemented")
        self.assertEqual(metadata["code_signing"], "not_configured")
        self.assertFalse(metadata["legal_decision_support"])
        expected_files = (executable, metadata_path, executable.with_name("THIRD-PARTY-NOTICES.txt"),
                          executable.with_name("payload-manifest.json"), executable.with_name("installer-build.json"))
        self.assertEqual(
            checksum_path.read_text(encoding="utf-8"),
            "".join(f"{package_metadata.file_hash(path)}  {path.name}\n" for path in expected_files),
        )
        self.assertNotIn(str(ROOT), metadata_path.read_text(encoding="utf-8"))
        self.assertNotIn(b"\r", checksum_path.read_bytes())

    def test_static_report_is_not_required_or_consumed(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        self.make_notices(executable)
        with mock.patch.object(package_metadata, "validate_models", return_value={}):
            metadata, _ = package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["static_analysis"], "not_run")
            executable.with_name("static-analysis.json").write_text("not a valid report", encoding="utf-8")
            self.make_build_record(executable, version="demo-2")
            metadata, checksum = package_metadata.write_metadata(executable, "demo-2", "a" * 40, self.approval)
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["static_analysis"], "not_run")
            self.assertNotIn("static-analysis.json", checksum.read_text(encoding="utf-8"))

    def test_missing_notices_prevent_metadata(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        with mock.patch.object(package_metadata, "validate_models", return_value={}):
            with self.assertRaises(FileNotFoundError):
                package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
        self.assertFalse(executable.with_name("release-metadata.json").exists())

    def test_approved_merged_source_record_is_preserved_and_must_match(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        self.make_notices(executable)
        record = self.approval_record
        with mock.patch.object(package_metadata, "validate_models", return_value={}):
            metadata, _ = package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["source_approval"], record)
            for key, value in [
                ("head_sha", "b" * 40), ("source_commit", "b" * 40),
                ("merged_to_default_branch", False), ("merge_method", "merge"), ("issue", 2),
            ]:
                self.approval.write_text(json.dumps({**record, key: value}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)

    def test_approval_is_required_by_api_and_cli(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        self.make_notices(executable)
        with mock.patch.object(package_metadata, "validate_models") as models:
            with self.assertRaises(TypeError):
                package_metadata.write_metadata(executable, "demo-1", "a" * 40)
            with self.assertRaisesRegex(ValueError, "approval"):
                package_metadata.write_metadata(executable, "demo-1", "a" * 40, None)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                package_metadata.main(["--exe", str(executable), "--version", "demo-1", "--commit", "a" * 40])
            self.assertEqual(failure.exception.code, 2)
        models.assert_not_called()
        self.assertFalse(executable.with_name("release-metadata.json").exists())

    def test_full_gate_provenance_must_match_installer_record_not_only_source(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        self.make_notices(executable)
        build_path = executable.with_name("installer-build.json")
        baseline = json.loads(build_path.read_text(encoding="utf-8"))
        with mock.patch.object(package_metadata, "validate_models", return_value={}):
            for key, value in [
                ("pull_request", 5), ("plan_blob_sha", "f" * 40),
                ("base_sha", "f" * 40), ("implementation_head_sha", "f" * 40),
                ("implementation_merged_by", "another-maintainer"),
                ("changed_files", ["run.py"]), ("repository", "example/other"),
            ]:
                record = {**self.approval_record, key: value}
                build_path.write_text(json.dumps({**baseline, "source_approval": record}), encoding="utf-8")
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "provenance differ"):
                    package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
            for key in ("repository", "plan_path"):
                build_path.write_text(json.dumps({**baseline, key: "other"}), encoding="utf-8")
                with self.subTest(identity=key), self.assertRaisesRegex(ValueError, "provenance differ"):
                    package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
        self.assertFalse(executable.with_name("release-metadata.json").exists())

    def test_legacy_unmerged_reports_and_missing_installer_provenance_are_rejected(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        self.make_notices(executable)
        build_path = executable.with_name("installer-build.json")
        baseline = json.loads(build_path.read_text(encoding="utf-8"))
        legacy = {
            "repository": "example/demo", "plan_path": "plans/1.json",
            "head_sha": "a" * 40, "merged_to_default_branch": False,
            "plan_approval_review_ids": [11], "implementation_approval_review_ids": [12],
        }
        self.approval.write_text(json.dumps(legacy), encoding="utf-8")
        with mock.patch.object(package_metadata, "validate_models", return_value={}):
            with self.assertRaises(ValueError):
                package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
            self.approval.write_text(json.dumps(self.approval_record), encoding="utf-8")
            for record in (None, legacy):
                build_path.write_text(json.dumps({**baseline, "source_approval": record}), encoding="utf-8")
                with self.subTest(record=record), self.assertRaises(ValueError):
                    package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
            del baseline["source_approval"]
            build_path.write_text(json.dumps(baseline), encoding="utf-8")
            with self.assertRaises(ValueError):
                package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)
        self.assertFalse(executable.with_name("release-metadata.json").exists())

    def test_missing_or_invalid_models_prevent_metadata(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        for error in (FileNotFoundError("Missing OCR assets"), ValueError("Model hash mismatch")):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                package_metadata, "validate_models", side_effect=error
            ), contextlib.redirect_stderr(io.StringIO()):
                result = package_metadata.main([
                    "--exe", str(executable), "--version", "demo-1", "--commit", "a" * 40,
                    "--approval", str(self.approval),
                ])
                self.assertEqual(result, 2)
                self.assertFalse(executable.with_name("release-metadata.json").exists())
                self.assertFalse(executable.with_name("SHA256SUMS.txt").exists())

    def test_script_entrypoints_resolve_repository_and_neighbor_imports(self):
        for name in (
            "packaging/package_metadata.py", "packaging/build_installer.py",
            "packaging/freeze_windows.py", ".github/scripts/approved_pr.py",
            ".github/scripts/check_public_content.py",
        ):
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, str(ROOT / name), "--help"],
                    cwd=self.directory, capture_output=True, text=True, check=True,
                )
                self.assertIn("--help", result.stdout)

    def test_invalid_metadata_arguments(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        for version, commit in (("demo\nx", "a" * 40), ("demo-1", "main")):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    package_metadata.write_metadata(executable, version, commit, self.approval)

    def test_metadata_accepts_only_the_installer_filename(self):
        for name in ("workflow-app.exe", "other-setup.exe"):
            executable = self.directory / name
            executable.write_bytes(b"synthetic")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "workflow-setup.exe"):
                package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)

    def test_wrong_or_executed_installer_build_record_fails(self):
        executable = self.directory / "workflow-setup.exe"
        executable.write_bytes(b"synthetic")
        self.make_notices(executable)
        record_path = executable.with_name("installer-build.json")
        baseline = json.loads(record_path.read_text(encoding="utf-8"))
        with mock.patch.object(package_metadata, "validate_models", return_value={}):
            for key, value in [
                ("source_commit", "b" * 40), ("installer_sha256", "0" * 64),
                ("payload_manifest_sha256", "0" * 64), ("payload_format", "onefile"),
                ("installer_executed", True), ("application_auto_run", True),
                ("policy_changes", True),
            ]:
                record_path.write_text(json.dumps({**baseline, key: value}), encoding="utf-8")
                with self.subTest(key=key), self.assertRaises(ValueError):
                    package_metadata.write_metadata(executable, "demo-1", "a" * 40, self.approval)


class PackagingTests(ProjectWorkspace):
    def make_assets(self):
        hashes = {model["filename"]: model["sha256"] for model in freeze_windows.MODELS}
        directory = self.directory / "assets"
        (directory / "licenses").mkdir(parents=True)
        for model in freeze_windows.MODELS:
            target = directory / model["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic-model")
        manifest = {
            "engine": "KLOCR", "version": freeze_windows.KLOCR_REVISION, "languages": ["ko", "en"],
            "device": "cpu", "runtime_downloads": False, "model_sha256": hashes,
            "source": "synthetic attribution fixture",
            "weights_license": "CC-BY-NC-SA-4.0", "license_review_required": True,
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        license_texts = (
            ("EasyOCR-LICENSE.txt", "Apache License"),
            ("CRAFT-LICENSE.txt", "Permission is hereby granted"),
            ("KLOCR-CC-BY-NC-SA-4.0.txt", "Attribution-NonCommercial-ShareAlike 4.0"),
        )
        for name, marker in license_texts:
            (directory / "licenses" / name).write_text(marker, encoding="utf-8")
        self.enterContext(mock.patch.object(freeze_windows, "LICENSES", {
            name: ("synthetic", hashlib.sha256(text.encode()).hexdigest())
            for name, text in license_texts
        }))
        return directory, hashes

    def test_assets_are_verified_and_allowlisted(self):
        directory, hashes = self.make_assets()
        (directory / "user_network").mkdir()
        (directory / "do-not-package.txt").write_text("synthetic", encoding="utf-8")
        with mock.patch.object(freeze_windows, "validate_models", return_value=hashes) as validate:
            assets = freeze_windows.selected_assets(directory)
        validate.assert_called_once_with(directory)
        self.assertEqual({path.relative_to(directory).as_posix() for path, _ in assets}, {
            *(model["filename"] for model in freeze_windows.MODELS),
            "manifest.json", *("licenses/" + name for name in freeze_windows.ASSET_LICENSES),
        })
        for source, destination in assets:
            self.assertEqual(
                destination,
                (Path("assets/klocr") / source.relative_to(directory).parent).as_posix(),
            )
        (directory / "licenses" / "CRAFT-LICENSE.txt").unlink()
        with mock.patch.object(freeze_windows, "validate_models", return_value=hashes):
            with self.assertRaises(FileNotFoundError):
                freeze_windows.selected_assets(directory)

    def test_unverified_model_or_manifest_fails_before_build(self):
        directory, hashes = self.make_assets()
        with mock.patch.object(freeze_windows, "validate_models", side_effect=ValueError("bad model")):
            with self.assertRaisesRegex(ValueError, "bad model"):
                freeze_windows.selected_assets(directory)
        (directory / "manifest.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(freeze_windows, "validate_models", return_value=hashes):
            with self.assertRaisesRegex(ValueError, "manifest"):
                freeze_windows.selected_assets(directory)

    def test_non_windows_build_refuses_cross_compilation_before_asset_access(self):
        with mock.patch.object(freeze_windows.sys, "platform", "darwin"), mock.patch.object(
            freeze_windows, "selected_assets"
        ) as assets, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(freeze_windows.main([]), 2)
        assets.assert_not_called()

    def test_arguments_collect_only_selected_assets_and_required_modules(self):
        dist = mock.Mock()
        for name in freeze_windows.EASYOCR_DATA:
            target = self.directory / "easyocr" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("synthetic characters", encoding="utf-8")
        dist.locate_file.side_effect = lambda path: self.directory / path
        asset = self.directory / "synthetic-model.pth"
        notices = self.directory / "THIRD-PARTY-NOTICES.txt"
        with mock.patch.object(freeze_windows.metadata, "distribution", return_value=dist):
            arguments = freeze_windows.build_arguments([(asset, "assets/klocr")], notices)
        for flag in ("--onedir", "--windowed", "--noupx"):
            self.assertIn(flag, arguments)
        self.assertNotIn("--onefile", arguments)
        self.assertNotIn("--runtime-tmpdir", arguments)
        self.assertEqual(arguments[arguments.index("--contents-directory") + 1], "_internal")
        self.assertEqual(arguments[arguments.index("--name") + 1], "workflow-app")
        self.assertNotIn("--console", arguments)
        self.assertNotIn("--collect-all", arguments)
        self.assertIn(f"{asset}:assets/klocr", arguments)
        self.assertTrue(all(module in arguments for module in freeze_windows.HIDDEN_IMPORTS))
        self.assertEqual(arguments[-1], str(ROOT / "run.py"))
        self.assertNotIn("user_network", " ".join(arguments))
        excluded = [
            arguments[index + 1] for index, arg in enumerate(arguments)
            if arg == "--exclude-module"
        ]
        self.assertIn("tests", excluded)
        self.assertIn("modules.ocr.prepare", excluded)
        self.assertNotIn("mock", excluded)
        self.assertNotIn("modules", excluded)
        for module in freeze_windows.FROZEN_OCR_MODULES:
            self.assertFalse(any(module == name or module.startswith(name + ".")
                                 for name in excluded), module)
        for module in ("modules.precedent", "modules.slm", "mock_server.server"):
            self.assertIn(module, freeze_windows.HIDDEN_IMPORTS)

    def frozen_archive(self, modules=None):
        reader = mock.MagicMock()
        archive = reader.CArchiveReader.return_value
        archive.toc = {"PYZ.pyz": (0, 0, 0, 0, "z")}
        pyz = archive.open_embedded_archive.return_value
        pyz.toc = {name: (0, 0, 1) for name in (
            freeze_windows.FROZEN_OCR_MODULES if modules is None else modules
        )}
        # Decoding the code object is allowed; executing it would fail this test.
        pyz.extract.return_value = compile("raise AssertionError('Do not execute')", "synthetic", "exec")
        executable = self.directory / "workflow-app.exe"
        executable.write_bytes(b"synthetic archive placeholder")
        return reader, archive, pyz, executable

    def test_frozen_audit_reads_bundled_bytecode_without_executing_it(self):
        reader, archive, pyz, executable = self.frozen_archive()
        with mock.patch.dict(sys.modules, {"PyInstaller.archive.readers": reader}):
            report = freeze_windows.verify_frozen_ocr_modules(executable)
        reader.CArchiveReader.assert_called_once_with(str(executable))
        archive.open_embedded_archive.assert_called_once_with("PYZ.pyz")
        self.assertEqual(pyz.extract.call_count, len(freeze_windows.FROZEN_OCR_MODULES))
        self.assertEqual(report["application_sha256"], hashlib.sha256(executable.read_bytes()).hexdigest())
        self.assertFalse(report["application_executed"])
        self.assertIn("torch.testing", report["required_modules"])

    def test_copied_sources_cannot_hide_missing_frozen_testing_module(self):
        modules = [name for name in freeze_windows.FROZEN_OCR_MODULES if name != "torch.testing"]
        reader, archive, pyz, executable = self.frozen_archive(modules)
        copied = self.directory / "_internal/torch/testing/__init__.py"
        copied.parent.mkdir(parents=True)
        copied.write_text("# Source file alone is not the frozen bytecode.\n", encoding="utf-8")
        with mock.patch.dict(sys.modules, {"PyInstaller.archive.readers": reader}):
            with self.assertRaisesRegex(ValueError, r"missing: torch\.testing"):
                freeze_windows.verify_frozen_ocr_modules(executable)
        pyz.extract.assert_not_called()

    def test_frozen_archive_missing_ambiguous_or_invalid_code_fails_closed(self):
        for mode in ("missing", "multiple", "empty_module", "corrupt"):
            reader, archive, pyz, executable = self.frozen_archive()
            if mode == "missing":
                archive.toc = {}
            elif mode == "multiple":
                archive.toc["another.pyz"] = (0, 0, 0, 0, "z")
            elif mode == "empty_module":
                pyz.extract.return_value = None
            else:
                pyz.extract.side_effect = ValueError("Corrupt bytecode")
            with self.subTest(mode=mode), mock.patch.dict(
                sys.modules, {"PyInstaller.archive.readers": reader},
            ), self.assertRaises(ValueError):
                freeze_windows.verify_frozen_ocr_modules(executable)

    def test_main_blocks_packaging_when_frozen_audit_fails(self):
        root = self.directory
        executable = root / "dist/workflow-app/workflow-app.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"not executable")
        torch = mock.Mock()
        torch.version.cuda = None
        builder = mock.Mock()
        with (
            mock.patch.object(freeze_windows, "ROOT", root),
            mock.patch.object(freeze_windows.sys, "platform", "win32"),
            mock.patch.object(freeze_windows.platform, "machine", return_value="AMD64"),
            mock.patch.object(freeze_windows, "selected_assets", return_value=[]),
            mock.patch.object(freeze_windows, "write_notices", return_value=root / "notice.txt"),
            mock.patch.object(freeze_windows, "build_arguments", return_value=["synthetic"]),
            mock.patch.dict(sys.modules, {"torch": torch, "PyInstaller.__main__": builder}),
            mock.patch.object(freeze_windows, "verify_frozen_ocr_modules",
                              side_effect=ValueError("Frozen OCR runtime modules missing: torch.testing")) as audit,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(freeze_windows.main([]), 2)
        builder.run.assert_called_once_with(["synthetic"])
        audit.assert_called_once_with(executable)
        self.assertFalse((root / "dist/frozen-ocr-audit.json").exists())

    def test_notices_include_nested_pdfium_and_upstream_license_texts(self):
        directory, hashes = self.make_assets()
        relative = "pypdfium2-5.11.0.dist-info/licenses/data/windows_x64/BUILD_LICENSES/pdfium.txt"
        license_path = self.directory / relative
        license_path.parent.mkdir(parents=True)
        license_path.write_text("Synthetic nested PDFium notice fixture.", encoding="utf-8")
        non_license = "packaging/licenses/__pycache__/__init__.cpython-312.pyc"
        code_path = self.directory / non_license
        code_path.parent.mkdir(parents=True)
        code_path.write_bytes(b"not a license: " + str(ROOT).encode())
        dist = mock.Mock()
        dist.metadata = mock.MagicMock()
        dist.metadata.__getitem__.return_value = "pypdfium2"
        dist.metadata.get.return_value = None
        dist.metadata.get_all.return_value = []
        dist.version = "5.11.0"
        dist.files = [relative, non_license]
        dist.locate_file.side_effect = lambda path: self.directory / path
        with mock.patch.object(freeze_windows, "validate_models", return_value=hashes):
            assets = freeze_windows.selected_assets(directory)
        path = freeze_windows.write_notices(self.directory / "THIRD-PARTY-NOTICES.txt", assets, [dist])
        text = path.read_text(encoding="utf-8")
        self.assertIn("Judicial Workflow", text)
        self.assertIn("Synthetic nested PDFium notice fixture.", text)
        self.assertIn("Apache License", text)
        self.assertIn("Permission is hereby granted", text)
        self.assertIn("not a legal opinion", text)
        self.assertNotIn(str(ROOT), text)
        self.assertNotIn("not a license:", text)
        self.assertTrue(all(model["url"] in text for model in freeze_windows.MODELS))


class WorkflowContractTests(unittest.TestCase):
    def test_tool_ownership_paths_and_no_packaging_package_shadow(self):
        expected = (
            "packaging/freeze_windows.py", "packaging/build_installer.py",
            "packaging/package_metadata.py", ".github/scripts/approved_pr.py",
            ".github/scripts/check_public_content.py", "modules/ocr/prepare.py",
            ".github/scripts/merged_build.py", ".github/scripts/review_scope.py",
            ".github/scripts/runtime_check.py",
        )
        for name in expected:
            with self.subTest(path=name):
                self.assertTrue((ROOT / name).is_file())
        self.assertFalse((ROOT / "packaging/__init__.py").exists())
        self.assertEqual(list((ROOT / "tools").glob("*.py")), [])

    def test_actions_are_pinned_and_execution_jobs_are_unprivileged(self):
        directory = ROOT / ".github/workflows"
        workflows = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
        required = {"ci.yml", "copilot-setup-steps.yml", "merged-build.yml",
                    "review-scope.yml", "windows-build.yml"}
        self.assertTrue(required <= {path.name for path in workflows},
                        "Required template workflows must not be removed.")
        for path in workflows:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                uses = re.findall(r"uses:\s*(\S+)", text)
                self.assertTrue(uses)
                self.assertTrue(all(re.fullmatch(r"actions/[\w-]+@[0-9a-f]{40}", use)
                                    or use == "./.github/workflows/windows-build.yml" for use in uses))
                self.assertIn("contents: read", text)
                self.assertIn("persist-credentials: false", text)
                self.assertNotIn("secrets.", text)
                self.assertNotIn("contents: write", text)
                self.assertNotIn("pull-requests: write", text)
                if path.name != "review-scope.yml":
                    self.assertNotIn("pull_request_target", text)

    def test_extra_workflows_are_checked_and_core_workflows_remain_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / ".github/workflows"
            directory.mkdir(parents=True)
            for path in (ROOT / ".github/workflows").glob("*.yml"):
                (directory / path.name).write_bytes(path.read_bytes())
            extra = directory / "extra.yaml"
            safe = ("permissions:\n  contents: read\nsteps:\n"
                    "  - uses: actions/checkout@" + "a" * 40
                    + "\n    with:\n      persist-credentials: false\n")
            def workflow_checks_pass():
                result = unittest.TestResult()
                WorkflowContractTests("test_actions_are_pinned_and_execution_jobs_are_unprivileged").run(result)
                return result.wasSuccessful()
            with mock.patch(__name__ + ".ROOT", root):
                extra.write_text(safe, encoding="utf-8")
                self.assertTrue(workflow_checks_pass())
                for unsafe in (safe.replace("@" + "a" * 40, "@main"),
                               safe.replace("contents: read", "contents: write")):
                    extra.write_text(unsafe, encoding="utf-8")
                    self.assertFalse(workflow_checks_pass())
                extra.write_text(safe, encoding="utf-8")
                (directory / "ci.yml").unlink()
                self.assertFalse(workflow_checks_pass())

    def test_reusable_build_has_explicit_artifact_allowlist(self):
        text = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_call:", text)
        self.assertNotIn("workflow_dispatch:", text)
        self.assertNotIn("\n  pull_request:\n", text)
        self.assertIn("ref: ${{ inputs.source_sha }}", text)
        self.assertNotIn("inspect_exe.py", text)
        self.assertNotIn("static-analysis.json", text)
        for command in re.findall(r"^\s+run:\s*(.+)$", text, re.MULTILINE):
            if ".exe" in command:
                self.assertTrue(command.startswith("python packaging/package_metadata.py "))
        self.assertNotIn("workflow-app.exe --self-test", text)
        self.assertNotIn("workflow-app.exe --ocr-self-test", text)
        self.assertNotIn("Start-Process", text)
        self.assertIn("timeout-minutes: 60", text)
        self.assertIn("retention-days: 14", text)
        files = re.search(r"          path: \|\n((?:            .+\n)+)", text)
        self.assertIsNotNone(files)
        self.assertEqual(files.group(1).split(), [
            "dist/workflow-setup.exe", "dist/release-metadata.json",
            "dist/SHA256SUMS.txt", "dist/THIRD-PARTY-NOTICES.txt",
            "dist/payload-manifest.json", "dist/installer-build.json",
            "dist/frozen-ocr-audit.json",
        ])
        self.assertNotIn("dist/*", text)
        self.assertNotIn("--windowed", text)
        self.assertNotIn("notify_release.py", text)
        self.assertIn('--commit "$env:APPROVED_HEAD"', text)
        self.assertNotIn('--commit "${{ github.sha }}"', text)
        self.assertNotIn("GH_TOKEN", text)
        self.assertNotIn("issues: write", text)
        self.assertIn("workflow-setup-pr-${{ inputs.pull_request }}-run-${{ github.run_number }}", text)

    def test_controller_and_notification_are_separate_from_execution(self):
        text = (ROOT / ".github/workflows/merged-build.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_run:", text)
        self.assertIn("!github.event.repository.is_template", text)
        self.assertNotIn("WORKFLOW_AUTOMATION_ENABLED", text)
        control, rest = text.split("\n  installer:", 1)
        self.assertNotIn("COPILOT_WORKFLOW_TOKEN", control)
        self.assertNotIn("COPILOT_WORKFLOW_TOKEN", rest)
        self.assertNotIn("pip install", control)
        self.assertNotIn("download-artifact", control)
        self.assertIn("ref: ${{ github.sha }}", control)
        self.assertIn("needs: control", rest)
        self.assertIn("needs.control.outputs.stage == 'build'", rest)
        self.assertIn("source_sha: ${{ needs.control.outputs.source }}", rest)
        self.assertIn('gh issue comment "$ISSUE"', rest)
        self.assertIn("needs.installer.outputs.artifact_url", rest)
        self.assertIn("outputs.stage == 'blocked'", rest)
        self.assertNotIn("issues: write", control)
        self.assertNotIn("types: [opened]", text)

    def test_scope_job_never_executes_pr_source(self):
        text = (ROOT / ".github/workflows/review-scope.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", text)
        self.assertIn("ref: ${{ github.sha }}", text)
        self.assertNotIn("pull_request.head.sha", text)
        self.assertNotIn("pip install", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("secrets.", text)

    def test_windows_cpu_install_and_offline_ocr_gates_are_ordered(self):
        text = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
        commands = [
            "python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu",
            "python -m pip install -r packaging/requirements.txt",
            "assert torch.version.cuda is None",
            "python .github/scripts/runtime_check.py --phase unit",
            "python run.py --self-test",
            "python modules/ocr/prepare.py",
            "python -m tests.ocr_check",
            "python .github/scripts/runtime_check.py --phase e2e",
            "python packaging/freeze_windows.py",
            "python packaging/build_installer.py",
            "python packaging/package_metadata.py",
            "uses: actions/upload-artifact@",
        ]
        offsets = [text.index(command) for command in commands]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(text.count('--unit-results "${{ runner.temp }}/unit-results.json"'), 2)
        self.assertIn("E2E tests (actual OCR, HTTP, GUI and export)", text)
        self.assertNotIn("--extra-index-url", text)
        self.assertNotIn("continue-on-error", text)

    def test_source_ci_avoids_push_and_ready_duplicates_for_pr_heads(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("types: [opened, synchronize, reopened]", text)
        self.assertIn("push:\n    branches: [main]", text)
        self.assertNotIn("ready_for_review", text)

    def test_ci_skips_only_plan_changes_and_keeps_build_trigger_in_sync(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        pr_events = text.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertTrue(text.startswith("name: CI\n"))
        self.assertIn("paths-ignore:\n      - 'plans/**'", pr_events)
        self.assertEqual(re.findall(r"^\s+- '([^']+)'$", pr_events, re.MULTILINE), ["plans/**"])
        self.assertIn("push:\n    branches: [main]", text)
        self.assertNotIn("paths-ignore", text.split("  push:\n", 1)[1])
        scope = (ROOT / ".github/workflows/review-scope.yml").read_text(encoding="utf-8")
        self.assertNotIn("paths-ignore", scope)
        build = (ROOT / ".github/workflows/merged-build.yml").read_text(encoding="utf-8")
        self.assertIn("workflows: [CI]", build)

    def test_basic_ci_remains_lightweight_without_ocr_downloads(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("python -m pip install -r modules/ocr/requirements-text.txt", text)
        self.assertIn("python .github/scripts/runtime_check.py --phase unit", text)
        self.assertIn("python run.py --self-test", text)
        for command in (
            "examples.", "pip install torch", "pip install -r requirements.txt",
            "pip install -r packaging/requirements.txt",
            "pip install -r modules/ocr/requirements.txt",
            "python modules/ocr/prepare.py", "--ocr-self-test",
        ):
            self.assertNotIn(command, text)

    def test_basic_ci_verifies_display_before_running_gui_unit_tests(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        commands = [
            "sudo apt-get update",
            "sudo apt-get install -y --no-install-recommends fonts-nanum xvfb xauth",
            "xvfb-run -a python - <<'PY'",
            "window = tk.Tk()",
            "window.update()",
            "window.destroy()",
            "run: xvfb-run -a python .github/scripts/runtime_check.py --phase unit",
        ]
        offsets = [text.index(command) for command in commands]
        self.assertEqual(offsets, sorted(offsets))
        for forbidden in ("continue-on-error", "|| true", "DISPLAY=", "--phase e2e"):
            self.assertNotIn(forbidden, text)
        self.assertEqual(text.count("runtime_check.py --phase unit"), 1)

    def test_agent_setup_prepares_real_offline_ocr_and_per_command_gui(self):
        text = (ROOT / ".github/workflows/copilot-setup-steps.yml").read_text(encoding="utf-8")
        self.assertIn("  copilot-setup-steps:", text)
        self.assertIn("runs-on: ubuntu-latest", text)
        self.assertIn("timeout-minutes: 59", text)
        self.assertIn('python-version: "3.12"', text)
        commands = [
            "sudo apt-get install -y --no-install-recommends fonts-nanum xvfb xauth",
            "python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu",
            "python -m pip install -r requirements.txt",
            "python -m pip check",
            "import torch, torchvision, easyocr, transformers, pypdfium2, PIL, numpy, cv2",
            "assert torch.version.cuda is None",
            "python modules/ocr/prepare.py",
            "xvfb-run -a python - <<'PY'",
            "ImageFont.truetype(str(sample_font()), 24)",
            "window = tk.Tk()",
            "window.destroy()",
            "python -m tests.ocr_check",
            "xvfb-run -a python .github/scripts/runtime_check.py --phase unit",
            "python run.py --self-test",
        ]
        offsets = [text.index(command) for command in commands]
        self.assertEqual(offsets, sorted(offsets))
        for forbidden in (
            "requirements-text.txt", "pip install -r packaging/requirements.txt", "--extra-index-url",
            "continue-on-error", "|| true", "JUDICIAL_RUNTIME_CHECKS",
            "--phase e2e", "DISPLAY=", "workflow-app.exe", "workflow-setup.exe",
        ):
            self.assertNotIn(forbidden, text)
        skill = (ROOT / ".github/skills/compose-workflow/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("xvfb-run -a python .github/scripts/runtime_check.py", skill)
        self.assertIn("not a scenario acceptance result", skill)


if __name__ == "__main__":
    unittest.main()
