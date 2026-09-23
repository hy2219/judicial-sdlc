"""Compile an Inno Setup installer from an approved merged-source onedir build. Never run Setup."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from modules.ocr.assets import ASSET_PATH, MODELS
from package_metadata import file_hash, validate_source_approval


def installer_identity(approval, commit, version):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full lowercase source commit is required.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", version):
        raise ValueError("Invalid installer version.")
    validate_source_approval(approval, commit)
    repo, plan = approval["repository"], approval["plan_path"]
    task_id = hashlib.sha256(f"{repo}:{plan}".encode()).hexdigest()[:12]
    slug = f"{task_id}-{commit[:12]}"
    return {
        "product_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/{repo}/{plan}@{commit}")),
        "product_slug": slug,
        "version": version,
        "source_commit": commit,
        "repository": repo,
        "plan_path": plan,
        "install_directory": f"%ProgramFiles%\\Judicial-SDLC\\{slug}",
        "requires_admin": True,
        "payload_format": "pyinstaller_onedir",
        "installer_format": "inno_setup",
        "application_auto_run": False,
        "policy_changes": False,
        "runtime_payload_self_extraction": False,
        "code_signing": "not_configured",
    }


def payload_files(payload, notices):
    """Inventory compiler input files, not binary instructions or signatures."""
    payload, notices = Path(payload), Path(notices)
    if not payload.is_dir() or not notices.is_file():
        raise FileNotFoundError("Directory payload and third-party notices are required.")
    if set(path.name for path in payload.iterdir()) != {"workflow-app.exe", "_internal"}:
        raise ValueError("Unexpected root content in the generated directory payload.")
    files = {}
    for path in payload.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Links and junctions cannot be included in the installer.")
        if path.is_file():
            files[path.relative_to(payload).as_posix()] = {
                "sha256": file_hash(path), "size_bytes": path.stat().st_size,
            }
    required = [
        "workflow-app.exe", "_internal/python312.dll",
        f"_internal/{ASSET_PATH}/manifest.json",
        "_internal/THIRD-PARTY-NOTICES.txt",
    ]
    if any(name not in files or not files[name]["size_bytes"] for name in required):
        raise ValueError("Runtime, notices or OCR manifest missing from directory payload.")
    for model in MODELS:
        entry = files.get(f"_internal/{ASSET_PATH}/" + model["filename"], {})
        if entry.get("sha256") != model["sha256"]:
            raise ValueError(f"Build payload model missing or changed: {model['filename']}")
    if files["_internal/THIRD-PARTY-NOTICES.txt"]["sha256"] != file_hash(notices):
        raise ValueError("External notices differ from payload notices.")
    return files


def compiler_path():
    located = shutil.which("ISCC.exe")
    if located:
        return Path(located)
    path = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"
    if not path.is_file():
        raise FileNotFoundError("Inno Setup 6 compiler is required on the Windows build runner.")
    return path


def compiler_arguments(compiler, identity, payload, output, notices, manifest):
    values = {
        "PayloadDir": str(Path(payload).resolve()),
        "OutputDir": str(Path(output).resolve()),
        "NoticeFile": str(Path(notices).resolve()),
        "PayloadManifest": str(Path(manifest).resolve()),
        "ProductId": identity["product_id"],
        "ProductSlug": identity["product_slug"],
        "PackageVersion": identity["version"],
    }
    if any(any(char in value for char in ('"', "\r", "\n", "\x00")) for value in values.values()):
        raise ValueError("Unsafe compiler definition.")
    return [str(compiler), "/Qp", *(f"/D{key}={value}" for key, value in values.items()),
            str(ROOT / "packaging" / "windows-installer.iss")]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--approval", type=Path, required=True)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("Installer build requires Windows; no installer was executed.", file=sys.stderr)
        return 2
    try:
        approval = json.loads(args.approval.read_text(encoding="utf-8"))
        identity = installer_identity(approval, args.commit, args.version)
        output = ROOT / "dist"
        payload, notices = output / "workflow-app", output / "THIRD-PARTY-NOTICES.txt"
        files = payload_files(payload, notices)
        manifest = output / "payload-manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 1, "source_commit": args.commit, "files": files,
            "scope": "input files staged for installer compilation; no installed application execution",
        }, indent=2) + "\n", encoding="utf-8")
        compiler = compiler_path()
        subprocess.run(compiler_arguments(compiler, identity, payload, output, notices, manifest), check=True)
        setup = output / "workflow-setup.exe"
        if not setup.is_file():
            raise FileNotFoundError("Inno Setup did not create workflow-setup.exe.")
        (output / "installer-build.json").write_text(json.dumps({
            **identity, "source_approval": approval,
            "payload_manifest_sha256": file_hash(manifest),
            "installer_sha256": file_hash(setup),
            "installer_executed": False, "application_executed": False,
        }, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Installer build failed: {exc}", file=sys.stderr)
        return 2
    print("Fixed-folder Setup compiled, NOT installed or executed. WDAC approval is separate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
