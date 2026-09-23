"""Small customization point. Add ordinary Python functions between module calls."""

from dataclasses import asdict

from modules.ocr import DocumentError, PageText


def demo_pages() -> list[PageText]:
    """A neutral input lets the empty shell run without any document or service."""
    return [PageText(1, "SYNTHETIC WORKSHOP ONLY\n여기에 필요한 업무 로직을 연결하세요.")]


def transform_pages(pages: list[PageText]) -> list[PageText]:
    """Replace or extend this function with the user's approved custom logic."""
    return pages


def run_pipeline(pages: list[PageText]) -> dict:
    """Default: show what was read. Search/SLM are optional, not always invoked."""
    result = transform_pages(pages)
    if not result:
        raise DocumentError("처리할 페이지가 없습니다.")
    return {
        "local_only": True,
        "notice": "기본 화면입니다. 판례검색·SLM은 아직 연결하지 않았습니다.",
        "pages": [asdict(page) for page in result],
    }
