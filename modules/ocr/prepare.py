"""Build-time model preparation. Never imported or called by the desktop app."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.ocr.assets import (
    ENGINE, KLOCR_REVISION, LICENSES, MODELS, model_directory, validate_models,
)

MAX_DOWNLOAD = 300 * 1024 * 1024


def download(url: str, target: Path, limit: int) -> None:
    with urlopen(url, timeout=120) as response, target.open("wb") as output:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError("Upstream asset exceeded the expected size limit")
            output.write(chunk)


def prepare(destination: Path, cache: Path | None = None) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ocr-build-") as temporary:
        temporary = Path(temporary)
        for model in MODELS:
            target = destination / model["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                with target.open("rb") as source:
                    if hashlib.file_digest(source, "sha256").hexdigest() == model["sha256"]:
                        continue
            extracted = temporary / model["filename"]
            extracted.parent.mkdir(parents=True, exist_ok=True)
            cached = cache / model["filename"] if cache else None
            if cached is not None and cached.is_file():
                shutil.copyfile(cached, extracted)
            elif model["url"].endswith(".zip"):
                zip_name = model["url"].rsplit("/", 1)[1]
                archive = cache / zip_name if cache and (cache / zip_name).is_file() else temporary / zip_name
                if not archive.exists():
                    download(model["url"], archive, MAX_DOWNLOAD)
                with ZipFile(archive) as bundle:
                    entry = bundle.getinfo(model["filename"])
                    if entry.file_size > MAX_DOWNLOAD or entry.is_dir():
                        raise ValueError("Unexpected model archive entry")
                    with bundle.open(entry) as source, extracted.open("wb") as output:
                        shutil.copyfileobj(source, output)
            else:
                download(model["url"], extracted, MAX_DOWNLOAD)
            with extracted.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest != model["sha256"]:
                raise ValueError(f"Unexpected upstream model content: {model['filename']}")
            shutil.copyfile(extracted, target)
        licenses = destination / "licenses"
        licenses.mkdir(exist_ok=True)
        for name, (url, expected_hash) in LICENSES.items():
            temporary_license = temporary / name
            download(url, temporary_license, 100_000)
            if hashlib.sha256(temporary_license.read_bytes()).hexdigest() != expected_hash:
                raise ValueError(f"Unexpected license content: {name}")
            shutil.copyfile(temporary_license, licenses / name)
    (destination / "user_network").mkdir(exist_ok=True)
    manifest = {
        "engine": ENGINE, "version": KLOCR_REVISION, "languages": ["ko", "en"],
        "device": "cpu", "runtime_downloads": False,
        "model_sha256": validate_models(destination),
        "source": "CRAFT detector / JHL3 KLOCR recognizer / team-lucid processor",
        "weights_license": "CC-BY-NC-SA-4.0",
        "license_review_required": True,
        "license_sha256": {name: digest for name, (_, digest) in LICENSES.items()},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="Optional local cache of pinned files or official ZIP archives")
    args = parser.parse_args()
    manifest = prepare(model_directory(), args.cache)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
