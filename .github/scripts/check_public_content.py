"""Small tracked-file preflight, not a comprehensive data-loss prevention system."""

import argparse
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


BLOCKED_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".heic", ".svg", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".hwp",
    ".hwpx", ".odt", ".rtf", ".zip", ".7z", ".rar", ".tar", ".gz", ".exe",
    ".dll", ".so", ".dylib", ".sqlite", ".db", ".pfx", ".p12", ".pem", ".key",
}
BLOCKED_DIRS = {
    "input", "inputs", "output", "outputs", "local", "local-data", "private",
    "uploads", "downloads", "dist", "build", ".venv", "venv", "node_modules",
    ".ssh", ".aws", ".azure", ".kube",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(
        r"""(?im)^\s*["']?(?:password|passwd|api_key|secret_key|(?:judicial_)?smtp_password|"""
        r"""access_token|client_secret|aws_secret_access_key)["']?\s*[:=]\s*["']([^"'\r\n]{8,})["']"""
    ),
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
PUBLIC_TEST_VALUES = {"synthetic-only", "demo-only", "not-configured", "not_configured"}


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError("Git metadata unavailable or unreadable; preflight failed.")
    return result.stdout


def content_reasons(data):
    reasons = set()
    if re.search(rb"(?m)^\s*%PDF-", data):
        reasons.add("PDF content is prohibited, including synthetic PDFs")
    if b"\x00" in data:
        reasons.add("binary content is prohibited")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return reasons | {"non-UTF-8/binary content is prohibited"}
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if match.lastindex and match.group(1).lower() in PUBLIC_TEST_VALUES:
                continue
            reasons.add("possible embedded credential or private key")
    for match in URL_PATTERN.finditer(text):
        try:
            url = urlsplit(match.group())
            host = (url.hostname or "").lower().rstrip(".")
            if url.username is not None or url.password is not None:
                reasons.add("URL contains embedded credentials")
            if host.endswith((".internal", ".local", ".corp", ".sharepoint.com")) or host in {
                "onedrive.live.com", "1drv.ms", "teams.microsoft.com", "teams.cloud.microsoft",
            }:
                reasons.add("possible private organization URL")
            try:
                address = ipaddress.ip_address(host)
                if address.is_private and not address.is_loopback:
                    reasons.add("private-network URL")
            except ValueError:
                pass
        except ValueError:
            reasons.add("malformed literal URL")
    return reasons


def path_reasons(name):
    path = Path(name)
    parts = [part.lower() for part in path.parts]
    reasons = set()
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        reasons.add("document, image, archive, binary or key file is prohibited")
    if any(part in BLOCKED_DIRS for part in parts[:-1]):
        reasons.add("local input/output or generated directory is prohibited")
    basename = parts[-1]
    if (
        basename == ".env" or basename.startswith(".env.")
        or basename.startswith(("credentials", "secrets"))
        or basename in {"id_rsa", "id_ed25519", ".npmrc", ".netrc", ".pypirc"}
    ):
        reasons.add("credential file is prohibited")
    return reasons


def audit(root):
    root = Path(root).resolve()
    top = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != root:
        raise RuntimeError("Target must be its own Git repository root; preflight failed.")
    records = git(root, "ls-files", "--stage", "-z").split(b"\x00")
    findings = set()
    count = 0
    for record in records:
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, object_id, stage = header.decode("ascii").split()
        name = raw_name.decode("utf-8", errors="surrogateescape")
        count += 1
        reasons = path_reasons(name)
        if stage != "0":
            reasons.add("unmerged index entry")
        if mode not in {"100644", "100755"}:
            reasons.add("symlinks and submodules are prohibited")
        else:
            reasons.update(content_reasons(git(root, "cat-file", "blob", object_id)))
            target = root / name
            relative_parents = Path(name).parents
            if target.is_symlink() or any((root / parent).is_symlink() for parent in relative_parents):
                reasons.add("tracked path resolves through a symlink")
            elif target.exists():
                try:
                    reasons.update(content_reasons(target.read_bytes()))
                except OSError:
                    reasons.add("tracked working-tree file is unreadable")
        findings.update((name, reason) for reason in reasons)
    if count == 0:
        raise RuntimeError("No tracked/index files; run git add before preflight.")
    return sorted(findings)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        findings = audit(args.root)
    except (RuntimeError, OSError) as exc:
        print(f"Preflight error: {exc}", file=sys.stderr)
        return 2
    for name, reason in findings:
        print(f"{json.dumps(name, ensure_ascii=True)}: {reason}")
    if findings:
        return 1
    print("Tracked working-tree and staged-blob preflight passed (not comprehensive DLP).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
