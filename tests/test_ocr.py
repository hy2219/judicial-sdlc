import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter

from tests.ocr_fixtures import make_text
from modules.ocr import (
    DocumentError, OCRUnavailable, PageText, SYNTHETIC_MARKER,
    ocr_page, read_document, render_page, validate_image_size,
)
from modules.ocr import assets, engine


def block(text, top=10, left=10, confidence=0.9):
    return {
        "text": text, "confidence": confidence,
        "box": [[left, top], [left + 100, top], [left + 100, top + 20], [left, top + 20]],
    }


class OCRTests(unittest.TestCase):
    def tearDown(self):
        engine.reader.cache_clear()

    def test_local_models_missing_and_tampered_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            data = b"synthetic weights for unit test only"
            pinned = ({"filename": "model.pth", "sha256": hashlib.sha256(data).hexdigest()},)
            with patch.object(assets, "MODELS", pinned):
                with self.assertRaises(FileNotFoundError):
                    assets.validate_models(directory)
                (directory / "model.pth").write_bytes(b"wrong")
                with self.assertRaises(ValueError):
                    assets.validate_models(directory)
                (directory / "model.pth").write_bytes(data)
                self.assertEqual(assets.validate_models(directory), {"model.pth": pinned[0]["sha256"]})

    def test_frozen_model_path_ignores_user_environment(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "_MEIPASS", "/synthetic-bundle", create=True
        ):
            self.assertEqual(assets.model_directory(), Path("/synthetic-bundle/assets/klocr"))

    def test_installed_onedir_models_are_inside_fixed_internal_folder(self):
        installed = Path("C:/Program Files/Judicial-SDLC/synthetic/_internal")
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "_MEIPASS", str(installed), create=True
        ):
            self.assertEqual(assets.model_directory(), installed / "assets/klocr")

    def test_reader_is_cpu_offline_and_clean_user_network(self):
        easyocr, torch, transformers = MagicMock(), MagicMock(), MagicMock()
        with (
            patch.dict(sys.modules, {"easyocr": easyocr, "torch": torch, "transformers": transformers}),
            patch.object(engine, "validate_models"),
            patch.object(engine, "model_directory", return_value=Path("/synthetic-models")),
        ):
            engine.reader()
            engine.reader()
        easyocr.Reader.assert_called_once()
        args, kwargs = easyocr.Reader.call_args
        self.assertEqual(args, (["ko", "en"],))
        self.assertFalse(kwargs["gpu"])
        self.assertFalse(kwargs["download_enabled"])
        self.assertFalse(kwargs["recognizer"])
        self.assertNotIn("recog_network", kwargs)
        self.assertEqual(kwargs["detect_network"], "craft")
        self.assertEqual(Path(kwargs["model_storage_directory"]), Path("/synthetic-models"))
        self.assertFalse(Path(kwargs["user_network_directory"]).exists())
        self.assertNotIn(kwargs["user_network_directory"], sys.path)
        torch.set_num_threads.assert_called_once_with(2)
        transformers.TrOCRProcessor.from_pretrained.assert_called_once_with(
            Path("/synthetic-models/processor"), local_files_only=True,
        )
        transformers.VisionEncoderDecoderModel.from_pretrained.assert_called_once_with(
            Path("/synthetic-models/model"), local_files_only=True, use_safetensors=True,
        )
        transformers.VisionEncoderDecoderModel.from_pretrained.return_value.to.assert_called_once_with("cpu")

    def test_crop_geometry_is_bounded_and_invalid_boxes_fail(self):
        regions = engine.crop_regions([[-2, 25, 4, 30]], [], (20, 20))
        self.assertEqual(regions[0][1], (0, 4, 20, 20))
        self.assertEqual(regions[0][0][0], [-2.0, 4.0])
        for boxes in (
            [[[0, 0], [float("nan"), 0], [10, 10], [0, 10]]],
            [[[50, 50], [60, 50], [60, 60], [50, 60]]],
            [[[0, 0], [10, 10]]],
        ):
            with self.subTest(boxes=boxes), self.assertRaises(ValueError):
                engine.crop_regions([], boxes, (20, 20))
        with patch.object(engine, "MAX_REGIONS", 0), self.assertRaises(ValueError):
            engine.crop_regions([[0, 10, 0, 10]], [], (20, 20))

    def test_grouping_retains_empty_recognition_and_truncation_warning(self):
        word = {**block(""), "warnings": ["generation truncated"]}
        result = engine.group_lines([word])[0]
        self.assertEqual(result["words"], [word])
        self.assertEqual(result["warnings"], ["generation truncated"])
        self.assertEqual(result["confidence_kind"], assets.CONFIDENCE_KIND)

    def test_same_line_words_preserve_source_and_confidence(self):
        words = [block("world", top=8, left=150, confidence=0.4), block("hello", top=10)]
        lines = engine.group_lines(words + [block("next", top=60)])
        self.assertEqual([line["text"] for line in lines], ["hello world", "next"])
        self.assertEqual(lines[0]["confidence"], 0.4)
        self.assertEqual(lines[0]["words"][0]["text"], "hello")

    def test_ocr_warnings_and_original_geometry(self):
        image = MagicMock()
        image.size = (1000, 700)
        with (
            patch("modules.ocr.assets.validate_models"),
            patch("modules.ocr.render_page", return_value=image),
            patch.object(engine, "recognize", return_value=[block("Synthetic original text", confidence=0.5)]),
        ):
            page = ocr_page(Path("synthetic.pdf"), 2)
        self.assertEqual(page.method, "klocr")
        self.assertEqual(page.image_size, (1000, 700))
        self.assertEqual(page.text, "Synthetic original text")
        self.assertTrue(any("낮은" in warning for warning in page.warnings))
        image.close.assert_called_once()
        self.assertEqual(page.blocks[0]["box"], block("Synthetic original text")["box"])
        self.assertEqual(page.blocks[0]["confidence"], 0.5)

    def test_missing_dependency_is_not_empty_success(self):
        with patch("modules.ocr.assets.validate_models"), patch(
            "modules.ocr.render_page", side_effect=ImportError("dependency unavailable")
        ):
            with self.assertRaises(OCRUnavailable):
                ocr_page(Path("synthetic.pdf"), 1)

    def test_blank_ocr_result_fails(self):
        image = MagicMock()
        image.size = (100, 100)
        with (
            patch("modules.ocr.assets.validate_models"),
            patch("modules.ocr.render_page", return_value=image),
            patch.object(engine, "recognize", return_value=[]),
        ):
            with self.assertRaisesRegex(DocumentError, "글자를 찾지"):
                ocr_page(Path("synthetic.pdf"), 1)

    def test_mixed_pdf_routes_only_required_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.pdf"
            make_text(path)
            writer = PdfWriter(clone_from=path)
            writer.add_blank_page(width=300, height=300)
            writer.add_metadata({"/JudicialSDLC": SYNTHETIC_MARKER})
            writer.write(Path(directory) / "with-blank.pdf")
            with patch("modules.ocr.ocr_page", return_value=PageText(3, "synthetic scan", "klocr")) as ocr:
                pages = read_document(Path(directory) / "with-blank.pdf")
            self.assertEqual([page.method for page in pages], ["pdf_text", "pdf_text", "klocr"])
            ocr.assert_called_once_with(Path(directory) / "with-blank.pdf", 3)

    def test_render_limit_checked_before_allocation_and_page_closed(self):
        pdfium = MagicMock()
        page = pdfium.PdfDocument.return_value.__enter__.return_value.__getitem__.return_value
        page.get_size.return_value = (1_000_000, 1_000_000)
        with patch.dict(sys.modules, {"pypdfium2": pdfium}):
            with self.assertRaisesRegex(DocumentError, "한도"):
                render_page(Path("synthetic.pdf"), 0)
        page.render.assert_not_called()
        page.close.assert_called_once()

    def test_a4_and_resource_boundaries(self):
        for size in ((1488, 2105), (2105, 1488), (1600, 2000), (2200, 1000)):
            with self.subTest(size=size):
                validate_image_size(*size)
        for size in ((2100, 2700), (1601, 2000), (2201, 1), (0, 100), (-1, 100)):
            with self.subTest(size=size), self.assertRaises(DocumentError):
                validate_image_size(*size)

    def test_oversized_recognition_fails_before_model_or_image_allocation(self):
        image = MagicMock(width=2100, height=2700)
        with patch.object(engine, "reader") as reader:
            with self.assertRaisesRegex(DocumentError, "처리 한도"):
                engine.recognize(image)
        reader.assert_not_called()
        image.convert.assert_not_called()

    def test_v2_sized_page_fails_before_rendering(self):
        pdfium = MagicMock()
        page = pdfium.PdfDocument.return_value.__enter__.return_value.__getitem__.return_value
        page.get_size.return_value = (840, 1080)
        with patch.dict(sys.modules, {"pypdfium2": pdfium}):
            with self.assertRaisesRegex(DocumentError, "처리 한도"):
                render_page(Path("synthetic.pdf"), 0)
        page.render.assert_not_called()
        page.close.assert_called_once()

    def test_detector_budget_preserves_original_image_and_crop_coordinates(self):
        image = MagicMock(width=1488, height=2105)
        rgb = image.convert.return_value.__enter__.return_value
        rgb.size = (1488, 2105)
        runtime = MagicMock()
        runtime.detector.detect.return_value = ([[[100, 300, 400, 450]]], [[]])
        runtime.processor.return_value.pixel_values = "synthetic-pixels"
        runtime.processor.batch_decode.return_value = ["SYNTHETIC"]
        output = runtime.model.generate.return_value
        output.sequences.shape = (1, 2)
        output.scores = []
        numpy, torch = MagicMock(), MagicMock()
        with (
            patch.dict(sys.modules, {"numpy": numpy, "torch": torch}),
            patch.object(engine, "reader", return_value=runtime),
            patch.object(engine, "sequence_confidence", return_value=(0.9, False)),
        ):
            lines = engine.recognize(image)
        runtime.detector.detect.assert_called_once_with(
            numpy.asarray.return_value, canvas_size=1536, mag_ratio=1.0,
        )
        rgb.resize.assert_not_called()
        rgb.crop.assert_called_once_with((100, 400, 300, 450))
        self.assertEqual(lines[0]["box"], [[100.0, 400.0], [300.0, 400.0],
                                          [300.0, 450.0], [100.0, 450.0]])
        rgb.crop.return_value.close.assert_called_once()

    def test_mixed_document_does_not_return_partial_success_after_oversized_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "text.pdf"
            mixed = Path(directory) / "mixed-oversized.pdf"
            make_text(path)
            writer = PdfWriter(clone_from=path)
            writer.add_blank_page(width=840, height=1080)
            writer.write(mixed)
            with patch("modules.ocr.assets.validate_models"), patch.object(
                engine, "reader",
            ) as reader:
                pdfium = MagicMock()
                page = pdfium.PdfDocument.return_value.__enter__.return_value.__getitem__.return_value
                page.get_size.return_value = (840, 1080)
                with patch.dict(sys.modules, {"pypdfium2": pdfium}):
                    with self.assertRaisesRegex(DocumentError, "3쪽.*처리 한도"):
                        read_document(mixed)
            reader.assert_not_called()
            page.render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
