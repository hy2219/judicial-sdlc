"""Generate neutral OCR test inputs; no scenario logic or binary files are shipped."""

import argparse
from pathlib import Path
import io
import os

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from modules.ocr import SYNTHETIC_MARKER

TEXT_PAGES = (
    "SYNTHETIC TEST DOCUMENT\nThe imaginary garden has blue flowers.\nA silver kite floats above a green hill.",
    "SYNTHETIC TEST DOCUMENT\nThe invented library has a round window.\nA small yellow boat rests beside the pond.",
)


def make_text(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_metadata({
        "/Title": "SYNTHETIC TEST - NOT A REAL DOCUMENT",
        "/JudicialSDLC": SYNTHETIC_MARKER,
    })
    for text in TEXT_PAGES:
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        commands = ["BT", "/F1 11 Tf", "40 790 Td", "20 TL"]
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.extend([f"({escaped}) Tj", "T*"])
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        page.replace_contents(stream)
    with path.open("xb") as output:
        writer.write(output)


def sample_font() -> Path:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "malgun.ttf",
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "합성 스캔 생성용 한국어 글꼴이 없습니다. Windows 맑은 고딕 또는 OS의 Noto/Nanum 글꼴이 필요합니다."
    )


def latin_sample_font() -> Path:
    for candidate in (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf",
        Path("/System/Library/Fonts/Menlo.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    ):
        if candidate.is_file():
            return candidate
    return sample_font()


def make_scan(path: Path, mixed: bool = False) -> None:
    """Render invented text into an image-only PDF; never use an existing document."""
    from PIL import Image, ImageDraw, ImageFont

    font = sample_font()
    image = Image.new("RGB", (1400, 720), "white")
    try:
        draw = ImageDraw.Draw(image)
        latin = ImageFont.truetype(str(latin_sample_font()), 44)
        korean = ImageFont.truetype(str(font), 48)
        draw.text((50, 40), "SYNTHETIC TEST DOCUMENT", font=latin, fill="black")
        draw.text((50, 130), "가상 교육 문서입니다", font=korean, fill="black")
        draw.text((50, 235), "The imaginary garden has blue flowers.", font=latin, fill="black")
        draw.text((50, 335), "A silver kite floats above a green hill.", font=latin, fill="black")
        draw.text((50, 435), "The invented library has a round window.", font=latin, fill="black")
        draw.text((50, 550), "한국어 영어 인식", font=korean, fill="black")
        encoded = io.BytesIO()
        image.save(encoded, format="PDF", resolution=180, quality=100, subsampling=0)
    finally:
        image.close()
    from pypdf import PdfReader
    writer = PdfWriter()
    if mixed:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="synthetic-text-") as temporary:
            text_path = Path(temporary) / "text.pdf"
            make_text(text_path)
            writer.add_page(PdfReader(text_path).pages[0])
    writer.add_page(PdfReader(encoded).pages[0])
    writer.add_metadata({
        "/Title": "SYNTHETIC SCAN - NOT A REAL DOCUMENT",
        "/JudicialSDLC": SYNTHETIC_MARKER,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        writer.write(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--text", type=Path)
    mode.add_argument("--scan", type=Path)
    args = parser.parse_args()
    if args.text:
        make_text(args.text)
    else:
        make_scan(args.scan)
