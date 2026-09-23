"""Pinned CRAFT/KLOCR weights and tokenizer assets; never downloaded at runtime."""

import hashlib
from pathlib import Path
import sys

KLOCR_REVISION = "54ee45d2f46639b6e99f2da63328d1ac88df684f"
PROCESSOR_REVISION = "33e0a37bee9b4715f974804a95e7e53323fbe4b7"
ENGINE = "KLOCR"
CONFIDENCE_KIND = "uncalibrated_geometric_mean_token_probability"
ASSET_PATH = "assets/klocr"
LICENSES = {
    "EasyOCR-LICENSE.txt": (
        "https://raw.githubusercontent.com/JaidedAI/EasyOCR/v1.7.2/LICENSE",
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    ),
    "CRAFT-LICENSE.txt": (
        "https://raw.githubusercontent.com/clovaai/CRAFT-pytorch/6c809d409996d4516e393f04e89965f070ecc14a/LICENSE",
        "bfecc97e4888896b7acf08534372baf25796b98c087ba5a424b46ee25adec871",
    ),
    "KLOCR-CC-BY-NC-SA-4.0.txt": (
        "https://raw.githubusercontent.com/creativecommons/cc-legal-tools-data/3edadd4e29295ef7c74d84e9949af826122066a8/docs/licenses/by-nc-sa/4.0/legalcode.txt",
        "e66c269d4819aaab34b49ef5220c4ddab6756f21bb5180761a4eb8561f2b7bbd",
    ),
}

_KLOCR_FILES = (
    ("config.json", "a7dba8f04bcbb57bc28bdeb72bf3744c81fc1feb6935794d0e37d6cbf1b47635"),
    ("generation_config.json", "257951071befdb57c88a45241ab2c426be95145cc65d63b294b27178e9b16a16"),
    ("model.safetensors", "1dfe9ff0be7b22e23df7e788cbc6f80268846d2de6fdd396a1eadf8d5170405f"),
    ("README.md", "353a95f665b311c9ee4c44739fa6e0151bb3cbae7ef3e0532e069cfdab33738c"),
)
_PROCESSOR_FILES = (
    ("preprocessor_config.json", "de5f3b46b8b2be82045620e2141b199a1a4ed3ce67aad9e965ecce29eb5688b2"),
    ("special_tokens_map.json", "06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f"),
    ("tokenizer.json", "ee6607aa19bbbf9e0894dfdc5c393516ea246e40cab7fbc3c05a06cc72fe1866"),
    ("tokenizer_config.json", "761f6f8afbe932fc87a736f91f032597ff6be5470d0a9d43f60d52f118c72723"),
    ("vocab.json", "7b7385c2484458551006f558d7171816b2216a0a0863538fb5e69f1ac1464321"),
    ("merges.txt", "23dbe86741adb0c54e86503ecaa2d2405cf320743528f5d2f3397c47dc1229b7"),
    ("README.md", "521b36afa6d7b5753908e54f6fb3cc2ba748873cd67b6ef57482d2c3ccc766ca"),
)

MODELS = (
    {
        "filename": "craft_mlt_25k.pth",
        "url": "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
        "md5": "2f8227d2def4037cdb3b34389dcf9ec1",
        "sha256": "4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17",
    },
) + tuple(
    {"filename": f"model/{name}",
     "url": f"https://huggingface.co/JHL3/KLOCR/resolve/{KLOCR_REVISION}/{name}",
     "sha256": digest}
    for name, digest in _KLOCR_FILES
) + tuple(
    {"filename": f"processor/{name}",
     "url": f"https://huggingface.co/team-lucid/trocr-small-korean/resolve/{PROCESSOR_REVISION}/{name}",
     "sha256": digest}
    for name, digest in _PROCESSOR_FILES
)


def model_directory() -> Path:
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    return root / ASSET_PATH


def validate_models(directory: Path | None = None) -> dict[str, str]:
    directory = model_directory() if directory is None else directory
    verified = {}
    for model in MODELS:
        path = directory / model["filename"]
        if not path.is_file():
            raise FileNotFoundError(
                f"KLOCR 구성 파일 {model['filename']}이 없습니다. "
                "개발 환경에서는 modules/ocr/prepare.py를 실행하고, 앱은 완전한 패키지로 다시 받으세요. "
                "실행 중에는 다운로드하지 않습니다."
            )
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != model["sha256"]:
            raise ValueError(f"KLOCR 구성 파일 무결성 오류: {model['filename']}. 다시 패키징해야 합니다.")
        verified[model["filename"]] = digest
    return verified


def available_status() -> str:
    return (
        "klocr_assets_present_unverified"
        if all((model_directory() / item["filename"]).is_file() for item in MODELS)
        else "klocr_assets_missing"
    )
