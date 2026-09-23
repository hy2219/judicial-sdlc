"""Build a fixed-folder Windows payload; never launch the resulting application."""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import sys
from types import CodeType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.ocr.assets import (
    ASSET_PATH, ENGINE, KLOCR_REVISION, LICENSES, MODELS, model_directory, validate_models,
)

RUNTIME_DISTRIBUTIONS = (
    "easyocr", "torch", "torchvision", "pypdfium2", "pypdf",
    "transformers", "tokenizers", "safetensors", "huggingface-hub",
)
ASSET_LICENSES = tuple(LICENSES)
EASYOCR_DATA = ("character/ko_char.txt", "character/en_char.txt")
HIDDEN_IMPORTS = (
    "modules.ocr.engine", "modules.precedent", "modules.slm", "mock_server.server",
    "easyocr.detection", "easyocr.craft",
    "torchvision._C", "pypdfium2", "pypdfium2_raw",
    "transformers.models.trocr.processing_trocr",
    "transformers.models.trocr.modeling_trocr",
    "transformers.models.vision_encoder_decoder.modeling_vision_encoder_decoder",
    "transformers.models.deit.modeling_deit",
    "transformers.models.deit.image_processing_deit",
    "transformers.models.roberta.tokenization_roberta",
    "tokenizers", "safetensors.torch",
)
FROZEN_OCR_MODULES = (
    "modules.ocr.engine", "easyocr.craft",
    "torch", "torch.nn", "torch.nn.functional", "torch.autograd.gradcheck",
    "torch.testing", "torch.testing._utils", "torch.testing._comparison",
    "torch.testing._creation",
    "transformers.models.vision_encoder_decoder.modeling_vision_encoder_decoder",
)


def validate_manifest(manifest, model_hashes):
    expected = {
        "engine": ENGINE, "version": KLOCR_REVISION, "languages": ["ko", "en"],
        "device": "cpu", "runtime_downloads": False, "model_sha256": model_hashes,
        "weights_license": "CC-BY-NC-SA-4.0", "license_review_required": True,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("OCR manifest does not match the reviewed configuration.")
    if not manifest.get("source"):
        raise ValueError("OCR manifest is missing source attribution.")


def selected_assets(directory=None):
    directory = model_directory() if directory is None else Path(directory)
    hashes = validate_models(directory)
    manifest_path = directory / "manifest.json"
    validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")), hashes)
    assets = [
        (directory / item["filename"], (Path(ASSET_PATH) / Path(item["filename"]).parent).as_posix())
        for item in MODELS
    ]
    assets.append((manifest_path, ASSET_PATH))
    for name in ASSET_LICENSES:
        path = directory / "licenses" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != LICENSES[name][1]:
            raise ValueError(f"Invalid attribution file: {name}")
        assets.append((path, ASSET_PATH + "/licenses"))
    return assets


def distribution_closure(roots=RUNTIME_DISTRIBUTIONS):
    from packaging.requirements import Requirement

    pending = [(name, frozenset()) for name in roots]
    visited = set()
    distributions = {}
    while pending:
        name, extras = pending.pop()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if (key, extras) in visited:
            continue
        visited.add((key, extras))
        dist = metadata.distribution(name)
        distributions[key] = dist
        for requirement in dist.requires or []:
            requirement = Requirement(requirement)
            if requirement.marker is None or any(
                requirement.marker.evaluate({"extra": extra}) for extra in extras | {""}
            ):
                pending.append((requirement.name, frozenset(requirement.extras)))
    # The bootloader is included, but PyInstaller's build-only dependencies are not.
    distributions["pyinstaller"] = metadata.distribution("pyinstaller")
    return [distributions[key] for key in sorted(distributions)]


def license_files(distribution):
    files = []
    for entry in distribution.files or []:
        parts = Path(str(entry).replace("\\", "/")).parts
        is_notice = parts[-1].lower().startswith(("license", "copying", "notice", "copyright"))
        in_notices = any(part.lower() in ("licenses", "build_licenses") for part in parts[:-1])
        if (is_notice or in_notices) and Path(parts[-1]).suffix.lower() not in (
            ".py", ".pyi", ".pyc", ".pyo", ".so", ".dll", ".exe",
        ):
            path = Path(distribution.locate_file(entry))
            if path.is_file():
                files.append((str(entry).replace("\\", "/"), path))
    return sorted(files)


def write_notices(destination, assets, distributions=None):
    distributions = distribution_closure() if distributions is None else distributions
    text = [
        "THIRD-PARTY NOTICES — local-document Judicial Workflow",
        "Collected installed-distribution notices and upstream model attribution.",
        "This is not a legal opinion, a complete SBOM, or a licensing certification.",
        "The distribution inventory follows declared runtime dependencies and the",
        "PyInstaller bootloader; optional hook-collected components can differ.",
        "No operating-system font is redistributed.",
        "",
        "OCR sources:",
        "EasyOCR 1.7.2: https://github.com/JaidedAI/EasyOCR/tree/v1.7.2",
        "CRAFT: https://github.com/clovaai/CRAFT-pytorch",
        f"KLOCR: https://huggingface.co/JHL3/KLOCR/tree/{KLOCR_REVISION}",
        "Processor: https://huggingface.co/team-lucid/trocr-small-korean",
        "KLOCR weights: CC-BY-NC-SA-4.0 (noncommercial/share-alike conditions).",
        "This package does not grant unrestricted commercial use or redistribution.",
        "Processor attribution: Apache-2.0; see bundled processor/README.md.",
        "Model attribution is preserved from upstream; weight/data rights require review.",
    ]
    for model in MODELS:
        text.extend([model["filename"], model["url"], f"SHA256: {model['sha256']}"])
    for path, _ in assets:
        if path.name in ASSET_LICENSES:
            text.extend(["", f"===== Upstream {path.name} =====", path.read_text(encoding="utf-8")])
    for dist in distributions:
        name = dist.metadata["Name"]
        text.extend(["", f"===== {name} {dist.version} ====="])
        for field in ("License-Expression", "License", "Home-page"):
            if dist.metadata.get(field):
                text.append(f"{field}: {dist.metadata[field]}")
        text.extend(f"Project-URL: {url}" for url in dist.metadata.get_all("Project-URL", []))
        notices = license_files(dist)
        if not notices:
            text.append("No installed license file found; see upstream project. Review required.")
        for relative, path in notices:
            text.extend([f"--- {relative} ---", path.read_text(encoding="utf-8", errors="replace")])
    prefix = Path(sys.base_prefix)
    runtime_notices = sorted(set(
        [path for path in (prefix / "LICENSE.txt", prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt") if path.is_file()]
        + list((prefix / "tcl").glob("*/license.terms"))
    ))
    text.extend(["", f"===== Python {platform.python_version()} / Tcl-Tk runtime ====="])
    for path in runtime_notices:
        text.extend([f"--- {path.relative_to(prefix).as_posix()} ---", path.read_text(encoding="utf-8", errors="replace")])
    if not runtime_notices:
        text.append("No local runtime license file found. Review Python/Tcl-Tk upstream notices.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(text) + "\n", encoding="utf-8")
    return destination


def build_arguments(assets, notices):
    arguments = [
        "--noconfirm", "--clean", "--onedir", "--windowed", "--noupx",
        "--contents-directory", "_internal",
        "--name", "workflow-app", "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
    ]
    for source, destination in [*assets, (notices, ".")]:
        arguments.extend(["--add-data", f"{source}:{destination}"])
    # Let the maintained torch/torchvision/PDFium hooks collect native libraries
    # and JIT sources, rather than copying site-packages or the entire virtualenv.
    for name in HIDDEN_IMPORTS:
        arguments.extend(["--hidden-import", name])
    for name in (
        "pypdfium2._helpers", "pypdfium2.internal", "transformers.models.trocr",
        "transformers.models.deit", "transformers.models.vision_encoder_decoder",
        "transformers.models.roberta",
    ):
        arguments.extend(["--collect-submodules", name])
    for name in ("torch", "torchvision", "pypdfium2_raw", "tokenizers", "safetensors"):
        arguments.extend(["--collect-binaries", name])
    for name in ("pypdfium2", "pypdfium2_raw"):
        arguments.extend(["--collect-data", name])
    easyocr = metadata.distribution("easyocr")
    for relative in EASYOCR_DATA:
        source = Path(easyocr.locate_file("easyocr/" + relative))
        if not source.is_file():
            raise FileNotFoundError(f"Missing EasyOCR runtime data: {relative}")
        arguments.extend(["--add-data", f"{source}:easyocr/{Path(relative).parent.as_posix()}"])
    for name in RUNTIME_DISTRIBUTIONS:
        arguments.extend(["--recursive-copy-metadata", name])
    for name in (
        "pytest", "IPython", "notebook", "matplotlib", "tensorboard",
        "easyocr.DBNet", "numpy.tests", "scipy.tests",
        "PIL.tests", "skimage.data", "tests", "modules.ocr.prepare",
    ):
        arguments.extend(["--exclude-module", name])
    arguments.append(str(ROOT / "run.py"))
    return arguments


def verify_frozen_ocr_modules(executable):
    """Inspect collected bytecode, not host imports or copied .py source files."""
    from PyInstaller.archive.readers import CArchiveReader

    executable = Path(executable)
    archive = CArchiveReader(str(executable))
    names = [name for name, entry in archive.toc.items() if entry[-1] == "z"]
    if len(names) != 1:
        raise ValueError("Expected exactly one embedded Python module archive.")
    pyz = archive.open_embedded_archive(names[0])
    missing = sorted(set(FROZEN_OCR_MODULES) - set(pyz.toc))
    if missing:
        raise ValueError("Frozen OCR runtime modules missing: " + ", ".join(missing))
    for name in FROZEN_OCR_MODULES:
        if not isinstance(pyz.extract(name), CodeType):
            raise ValueError(f"Frozen OCR module has no readable bytecode: {name}")
    with executable.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "application_sha256": digest,
        "required_modules": list(FROZEN_OCR_MODULES),
        "status": "required_bytecode_present",
        "application_executed": False,
        "limitation": "Static archive inspection only; Windows DLL loading and OCR execution remain unverified.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        print("Build error: an AMD64 Windows Python environment is required; no cross-compilation.", file=sys.stderr)
        return 2
    try:
        assets = selected_assets()
        import torch
        if torch.version.cuda is not None:
            raise ValueError("Only CPU PyTorch wheels may be packaged.")
        notices = write_notices(ROOT / "dist" / "THIRD-PARTY-NOTICES.txt", assets)
        from PyInstaller.__main__ import run
        run(build_arguments(assets, notices))
        executable = ROOT / "dist" / "workflow-app" / "workflow-app.exe"
        if not executable.is_file():
            raise RuntimeError("PyInstaller did not produce the expected directory payload.")
        audit = verify_frozen_ocr_modules(executable)
        (ROOT / "dist" / "frozen-ocr-audit.json").write_text(
            json.dumps(audit, indent=2) + "\n", encoding="utf-8",
        )
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"Build error: {exc}", file=sys.stderr)
        return 2
    print("Frozen OCR bytecode checked; Windows directory payload NOT executed. Build its installer next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
