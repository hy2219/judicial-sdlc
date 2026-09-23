"""Local text-PDF reading and offline CRAFT/KLOCR."""

from dataclasses import dataclass
import math
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SYNTHETIC_MARKER = "JUDICIAL-SDLC-SYNTHETIC-V1"
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 100
MAX_RENDER_PIXELS = 3_200_000
MAX_RENDER_EDGE = 2200
RENDER_SCALE = 2.5


class DocumentError(ValueError):
    pass


class OCRUnavailable(DocumentError):
    pass


def validate_image_size(width: int, height: int) -> None:
    if (
        min(width, height) <= 0
        or max(width, height) > MAX_RENDER_EDGE
        or width * height > MAX_RENDER_PIXELS
    ):
        raise DocumentError(
            "OCR 이미지가 실습 처리 한도(320만 픽셀·한 변 2200픽셀)를 초과했습니다. "
            "원본을 보존하고 A4 크기의 별도 사본으로 준비하세요. "
            "페이지를 생략하거나 일부 결과를 완료로 처리하지 않았습니다."
        )


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    method: str = "pdf_text"
    blocks: tuple[dict, ...] = ()
    image_size: tuple[int, int] | None = None
    warnings: tuple[str, ...] = ()


def render_page(path: Path, page_index: int):
    import pypdfium2

    with pypdfium2.PdfDocument(path) as document:
        page = document[page_index]
        try:
            width, height = page.get_size()
            if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                raise DocumentError("OCR 페이지 크기가 올바르지 않습니다.")
            validate_image_size(
                math.ceil(width * RENDER_SCALE), math.ceil(height * RENDER_SCALE),
            )
            bitmap = page.render(scale=RENDER_SCALE)
            try:
                return bitmap.to_pil().convert("RGB").copy()
            finally:
                bitmap.close()
        finally:
            page.close()


def ocr_page(path: Path, page_number: int) -> PageText:
    from modules.ocr.assets import validate_models

    try:
        validate_models()
        from modules.ocr.engine import recognize
        image = render_page(path, page_number - 1)
        try:
            image_size = image.size
            blocks = recognize(image)
        finally:
            image.close()
    except (ImportError, FileNotFoundError) as exc:
        raise OCRUnavailable(f"{page_number}쪽: KLOCR 구성요소 또는 모델이 없습니다. {exc}") from exc
    except (RuntimeError, ValueError, OSError) as exc:
        raise DocumentError(f"{page_number}쪽: 로컬 OCR 처리 실패. {exc}") from exc
    if not blocks:
        raise DocumentError(f"{page_number}쪽: OCR에서 글자를 찾지 못했습니다. 원문을 확인하세요.")
    warnings = [
        "OCR 결과는 원문 대조가 필요합니다. 앱 줄번호는 단일 열 가로쓰기 기준이며 다단·표 읽기 순서를 보장하지 않습니다.",
        "KLOCR 신뢰도는 토큰 확률 기반의 비보정 지표이며 정확도 확률이 아닙니다.",
    ]
    if any(block["confidence"] < 0.6 for block in blocks):
        warnings.append("낮은 인식 신뢰도의 영역이 있습니다. 자동 정정하지 않았습니다.")
    warnings.extend(dict.fromkeys(warning for block in blocks for warning in block.get("warnings", [])))
    text = "\n".join(block["text"] for block in blocks)
    if len(text) > 50_000:
        raise DocumentError(f"{page_number}쪽의 OCR 결과가 실습 한도를 초과했습니다.")
    return PageText(page_number, text, "klocr", tuple(blocks), image_size, tuple(warnings))


def read_document(path: Path, *, synthetic_only: bool = False) -> list[PageText]:
    """Read a local PDF without uploads; optionally require a generated test marker."""
    if path.suffix.lower() != ".pdf":
        raise DocumentError("PDF 파일만 선택하세요.")
    if path.stat().st_size > MAX_PDF_BYTES:
        raise DocumentError("PDF는 50MB 이하만 지원합니다.")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise DocumentError("암호화된 PDF는 이 실습에서 지원하지 않습니다.")
        if synthetic_only and (reader.metadata or {}).get("/JudicialSDLC") != SYNTHETIC_MARKER:
            raise DocumentError(
                "합성 자료 전용 시험에서는 합성 표시가 있는 PDF만 사용할 수 있습니다."
            )
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise DocumentError("PDF는 1~100페이지만 지원합니다.")
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            resources = page.get("/Resources")
            resources = resources.get_object() if resources else {}
            xobjects = resources.get("/XObject", {})
            xobjects = xobjects.get_object() if xobjects else {}
            content = page.get_contents()
            has_inline_image = content is not None and any(
                operator == b"INLINE IMAGE" for _, operator in content.operations
            )
            if page.get("/Annots"):
                raise DocumentError(f"{number}쪽: 주석/양식이 있는 PDF는 이 실습에서 지원하지 않습니다.")
            if xobjects or has_inline_image:
                pages.append(ocr_page(path, number))
                continue
            if not text.strip():
                pages.append(ocr_page(path, number))
                continue
            if len(text) > 50_000:
                raise DocumentError(f"{number}쪽의 텍스트가 실습 한도를 초과했습니다.")
            pages.append(PageText(number, text))
        return pages
    except PdfReadError as exc:
        raise DocumentError("PDF를 읽을 수 없습니다.") from exc
