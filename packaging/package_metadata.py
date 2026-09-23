"""Record installer provenance and checksums without installing or running it."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.ocr.assets import CONFIDENCE_KIND, ENGINE, KLOCR_REVISION, validate_models


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_source_approval(record, commit):
    """Validate trusted gate provenance; GitHub merge verification belongs to the gate."""
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("Expected the full 40-character source commit.")
    if not isinstance(record, dict):
        raise ValueError("Trusted merged-source approval metadata is required.")
    for field in ("issue", "pull_request"):
        if type(record.get(field)) is not int or record[field] <= 0:
            raise ValueError(f"Positive integer {field} is required.")
    if (
        record.get("plan_approval") != "manual_pr_comment_not_machine_verified"
        or any(field in record for field in ("plan_pull_request", "plan_merge_sha", "plan_merged_by"))
    ):
        raise ValueError("Expected single-PR provenance with an explicit manual plan-review boundary.")
    repository = record.get("repository")
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("Invalid source repository.")
    if record.get("plan_path") != f"plans/{record['issue']}.json":
        raise ValueError("Approved plan path must match the issue.")
    for field in (
        "plan_blob_sha", "base_sha", "implementation_head_sha", "head_sha", "source_commit",
    ):
        value = record.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", value):
            raise ValueError(f"Full {field} is required.")
    if (
        record["head_sha"].lower() != commit.lower()
        or record["source_commit"].lower() != commit.lower()
        or record.get("merged_to_default_branch") is not True
        or record.get("merge_method") != "squash"
    ):
        raise ValueError("Approval must identify the exact squash commit merged to the default branch.")
    login = record.get("implementation_merged_by")
    if (
        not isinstance(login, str) or not login or not login.isprintable()
        or any(char.isspace() for char in login) or login.lower().endswith("[bot]")
    ):
        raise ValueError("Human implementation_merged_by login is required.")
    changed_files = record.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        raise ValueError("Changed source files are required.")
    for path in changed_files:
        if (
            not isinstance(path, str) or not path or not path.isprintable()
            or "\\" in path or any(part in ("", ".", "..") for part in path.split("/"))
        ):
            raise ValueError("Changed source files must be safe repository-relative paths.")
    return record


def write_metadata(executable, version, commit, approval):
    executable = Path(executable)
    if executable.name != "workflow-setup.exe" or not executable.is_file():
        raise ValueError("Expected an existing workflow-setup.exe.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", version):
        raise ValueError("Invalid version.")
    if approval is None:
        raise ValueError("Trusted merged-source approval metadata is required.")
    source_approval = validate_source_approval(
        json.loads(Path(approval).read_text(encoding="utf-8")), commit,
    )
    model_hashes = validate_models()
    digest = file_hash(executable)
    notices = executable.with_name("THIRD-PARTY-NOTICES.txt")
    notices_hash = file_hash(notices)
    build_path = executable.with_name("installer-build.json")
    manifest_path = executable.with_name("payload-manifest.json")
    build = json.loads(build_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(build, dict) or not isinstance(manifest, dict)
        or build.get("source_commit") != commit.lower() or build.get("version") != version
        or build.get("installer_sha256") != digest
        or build.get("payload_manifest_sha256") != file_hash(manifest_path)
        or build.get("payload_format") != "pyinstaller_onedir"
        or build.get("installer_format") != "inno_setup"
        or build.get("installer_executed") is not False
        or build.get("application_executed") is not False
        or build.get("application_auto_run") is not False
        or build.get("policy_changes") is not False
        or manifest.get("source_commit") != commit.lower()
    ):
        raise ValueError("Installer build record does not match these unexecuted output files.")
    build_approval = validate_source_approval(build.get("source_approval"), commit)
    if (
        build_approval != source_approval
        or build.get("repository") != source_approval["repository"]
        or build.get("plan_path") != source_approval["plan_path"]
    ):
        raise ValueError("Installer identity and merged-source approval provenance differ.")
    metadata = {
        "schema_version": 10,
        "version": version,
        "source_commit": commit.lower(),
        "source_approval": source_approval,
        "filename": executable.name,
        "sha256": digest,
        "platform": "windows",
        "mode": "mock-only",
        "synthetic_documents_only": False,
        "document_processing": "local_only",
        "console_window": False,
        "diagnostics": "local_error_types_and_code_locations_only",
        "built_executable_executed": False,
        "installer_executed": False,
        "application_executed": False,
        "static_analysis": "not_run",
        "runtime_behavior_verified": False,
        "third_party_notices_sha256": notices_hash,
        "packaging": {
            "type": "fixed_folder_installer",
            "payload_format": "pyinstaller_onedir",
            "install_directory": build.get("install_directory"),
            "product_id": build.get("product_id"),
            "requires_admin": True,
            "application_auto_run": False,
            "policy_changes": False,
            "wdac_approval": "not_granted_by_this_package",
            "payload_manifest_sha256": file_hash(manifest_path),
            "installer_build_sha256": file_hash(build_path),
        },
        "ocr": {
            "engine": ENGINE,
            "version": KLOCR_REVISION,
            "languages": ["ko", "en"],
            "device": "cpu",
            "gpu": False,
            "runtime_downloads": False,
            "detector": "CRAFT",
            "recognizer": "JHL3/KLOCR",
            "confidence_kind": CONFIDENCE_KIND,
            "weights_license": "CC-BY-NC-SA-4.0",
            "license_review_required": True,
            "model_sha256": model_hashes,
            "model_hash_scope": "verified_build_inputs_and_staged_payload_not_installed_runtime",
        },
        "legal_decision_support": False,
        "antivirus_scan": "not_implemented",
        "dynamic_sandbox": "not_implemented",
        "code_signing": "not_configured",
        "limitations": [
            "Plan approval is a manual PR-comment process, not a machine-verified approval record.",
            "Only build-input models and output file checksums are recorded.",
            "Neither installer nor installed application was executed; install/uninstall and DLL loading are unverified.",
            "The installer may use setup-time temporary files; runtime payload resides in the installed directory.",
            "WDAC approval/signing requirements remain the organization's decision; no policy bypass is provided.",
            "No final binary static analysis, antivirus, sandbox, security, or licensing certification.",
            "KLOCR weights have noncommercial/share-alike conditions; review rights before use or redistribution.",
        ],
    }
    metadata_path = executable.with_name("release-metadata.json")
    checksum_path = executable.with_name("SHA256SUMS.txt")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    checksum_path.write_text(
        "".join(f"{file_hash(path)}  {path.name}\n" for path in
                (executable, metadata_path, notices, manifest_path, build_path)),
        encoding="ascii", newline="\n",
    )
    return metadata_path, checksum_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument(
        "--approval", type=Path, required=True,
        help="Trusted workflow approval record for the merged squash commit",
    )
    args = parser.parse_args(argv)
    try:
        paths = write_metadata(args.exe, args.version, args.commit, args.approval)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Metadata error: {exc}", file=sys.stderr)
        return 2
    print("\n".join(str(path) for path in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
