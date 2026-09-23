"""Source-only OCR acceptance check on locally generated fictional text."""

import json
from pathlib import Path
import socket
import tempfile
from unittest.mock import patch

from tests.ocr_fixtures import TEXT_PAGES, make_scan, make_text
from modules.ocr import read_document
from modules.ocr.assets import CONFIDENCE_KIND, validate_models
from modules.ocr.engine import reader


def check_text_rendering(path: Path):
    import pypdfium2

    with pypdfium2.PdfDocument(path) as document:
        if len(document) != len(TEXT_PAGES):
            raise RuntimeError("Rendered text PDF page count changed.")
        for index, expected in enumerate(TEXT_PAGES):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    actual = text_page.get_text_range()
                    if actual.split() != expected.split():
                        raise RuntimeError("Independent PDF renderer could not read the generated text.")
                finally:
                    text_page.close()
                bitmap = page.render(scale=1)
                try:
                    image = bitmap.to_pil()
                    if not any(low < high for low, high in image.getextrema()):
                        raise RuntimeError("Generated text PDF renders as a blank page.")
                finally:
                    bitmap.close()
            finally:
                page.close()


def check_offline_ocr() -> dict:
    validate_models()
    reader.cache_clear()
    with tempfile.TemporaryDirectory(prefix="judicial-synthetic-scan-") as directory:
        text_path = Path(directory) / "text.pdf"
        make_text(text_path)
        check_text_rendering(text_path)
        path = Path(directory) / "mixed-demo.pdf"
        make_scan(path, mixed=True)

        def deny_network(*_args, **_kwargs):
            raise RuntimeError("OCR attempted a network connection")

        with (
            patch.object(socket.socket, "connect", deny_network),
            patch.object(socket.socket, "connect_ex", deny_network),
            patch.object(socket, "create_connection", deny_network),
        ):
            pages = read_document(path)
            if reader().device != "cpu" or reader().download_enabled:
                raise RuntimeError("OCR is not configured as offline CPU")
        if [page.method for page in pages] != ["pdf_text", "klocr"]:
            raise RuntimeError("Mixed text/scan routing failed")
        scan = pages[1]
        compact = "".join(scan.text.split()).lower()
        if not all(word in compact for word in ("가상교육문서", "한국어", "imaginarygarden", "silver")):
            raise RuntimeError("Synthetic Korean/English OCR did not meet the expected text checks")
        if not scan.blocks or not scan.image_size:
            raise RuntimeError("OCR provenance is missing")
        for line in scan.blocks:
            if line.get("confidence_kind") != CONFIDENCE_KIND or not line.get("words"):
                raise RuntimeError("KLOCR confidence semantics or source regions are missing")
            for word in line["words"]:
                if word.get("recognizer") != "KLOCR" or not 0 <= word["confidence"] <= 1:
                    raise RuntimeError("Unexpected recognizer or invalid token confidence")
                if word.get("warnings"):
                    raise RuntimeError("Synthetic OCR has an incomplete recognition region")
        return {
            "synthetic_only": True,
            "engine": "CRAFT + KLOCR / CPU / ko,en",
            "network_connections_during_ocr": "blocked",
            "page_methods": [page.method for page in pages],
            "ocr_blocks": len(scan.blocks),
            "text_pdf_independent_rendering": "passed",
            "notice": "Source-only OCR module check. No generated executable was run.",
        }


if __name__ == "__main__":
    print(json.dumps(check_offline_ocr(), ensure_ascii=False, indent=2))
