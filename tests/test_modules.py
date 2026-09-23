from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlunsplit

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

from tests.ocr_fixtures import TEXT_PAGES, make_text
from mock_server.fixtures import CLAIMS, SOURCE_TEXT
from mock_server.server import running_server
from modules.ocr import DocumentError, OCRUnavailable, SYNTHETIC_MARKER, read_document
from modules.precedent import login, search
from modules.slm import compare_claim
from modules.transport import MockConnection, ServiceError


class ModuleTests(unittest.TestCase):
    def test_scenario_sources_use_real_http_and_preserve_lookup_states(self):
        sources = {
            "SYNTHETIC-A": {"title": "Fictional record", "text": "A blue workshop door.",
                            "location": "Synthetic paragraph 1"},
            "SYNTHETIC-B": None,
        }
        with running_server(sources=sources) as (url, key, events):
            connection = MockConnection(url, key)
            with self.assertRaises(ServiceError):
                search(connection, "SYNTHETIC-A")
            login(connection)
            sources["SYNTHETIC-A"]["text"] = "Changed after server start."
            found = search(connection, "SYNTHETIC-A")
            self.assertEqual(found["source"], {
                "id": "SYNTHETIC-A", "title": "Fictional record",
                "text": "A blue workshop door.", "location": "Synthetic paragraph 1",
                "authority": "mock_fixture_only",
            })
            self.assertTrue(found["mock"])
            self.assertEqual(search(connection, "SYNTHETIC-B")["status"], "no_hit")
            self.assertEqual(search(connection, "SYNTHETIC-C")["status"], "fixture_not_configured")
            self.assertEqual(search(connection, "DEMO-001")["status"], "fixture_not_configured")
            self.assertEqual(compare_claim(
                connection, "DEMO-001", CLAIMS["DEMO-001"], SOURCE_TEXT["DEMO-001"],
            )["status"], "insufficient_basis")
            self.assertEqual([e["path"] for e in events], [
                "/session", "/precedents/search", "/precedents/search",
                "/precedents/search", "/precedents/search", "/slm/compare",
            ])
            self.assertFalse(any("token" in event or "text" in event for event in events))
        with running_server() as (url, key, _):
            connection = MockConnection(url, key)
            login(connection)
            self.assertEqual(search(connection, "SYNTHETIC-A")["status"], "fixture_not_configured")
            self.assertEqual(search(connection, "DEMO-001")["status"], "found")

    def test_custom_sources_validate_before_start_and_failures_stay_distinct(self):
        invalid = [
            [], {"": None}, {1: None}, {"x" * 8001: None}, {"A": "raw text"},
            {"A": {"title": "t", "text": "text"}}, {"A": {"title": "t", "text": "", "location": "p"}},
            {"A": {"title": "t", "text": "text", "location": 1}},
            {"A": {"title": "t", "text": "text", "location": "p", "authority": "official"}},
            {"A": {"title": "t", "text": "가" * 11000, "location": "p"}},
        ]
        for value in invalid:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                with running_server(sources=value):
                    self.fail("Invalid sources must not start a server.")
        with running_server(sources={}) as (url, key, _):
            connection = MockConnection(url, key)
            login(connection)
            self.assertEqual(search(connection, "DEMO-001")["status"], "fixture_not_configured")
        for mode in ("expired", "unavailable"):
            with self.subTest(mode=mode), running_server(mode, sources={"A": None}) as (url, key, _):
                connection = MockConnection(url, key)
                login(connection)
                with self.assertRaises(ServiceError):
                    search(connection, "A")

    def test_lookup_outcomes_over_real_loopback_http(self):
        with running_server() as (url, key, events):
            connection = MockConnection(url, key)
            login(connection)
            for case_id, status in (("DEMO-001", "found"), ("DEMO-003", "no_hit"),
                                    ("DEMO-999", "fixture_not_configured")):
                self.assertEqual(search(connection, case_id)["status"], status)
            self.assertEqual(len(events), 4)

    def test_comparison_fixture_contract_and_abstention(self):
        with running_server() as (url, key, _events):
            connection = MockConnection(url, key)
            login(connection)
            for case_id, status in (("DEMO-001", "supported"), ("DEMO-002", "discrepancy")):
                self.assertEqual(compare_claim(
                    connection, case_id, CLAIMS[case_id], SOURCE_TEXT[case_id],
                )["status"], status)
            self.assertEqual(compare_claim(
                connection, "DEMO-001", "changed claim", SOURCE_TEXT["DEMO-001"],
            )["status"], "insufficient_basis")

    def test_synthetic_pdf_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "generated.pdf"
            make_text(path)
            before = path.read_bytes()
            pages = read_document(path)
            self.assertEqual([page.text.strip() for page in pages], list(TEXT_PAGES))
            self.assertEqual([page.page for page in pages], [1, 2])
            self.assertTrue(all("DEMO-" not in page.text for page in pages))
            for page in PdfReader(path, strict=True).pages:
                self.assertIsInstance(page.raw_get("/Contents"), IndirectObject)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(FileExistsError):
                make_text(path)

    def test_unmarked_pdf_is_rejected_only_in_explicit_synthetic_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            writer.write(path)
            with self.assertRaisesRegex(DocumentError, "합성 자료 전용"):
                read_document(path, synthetic_only=True)

    def test_ordinary_unmarked_pdf_and_longer_document_are_read_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unmarked.pdf"
            marked = Path(directory) / "marked.pdf"
            make_text(marked)
            source = PdfReader(marked)
            writer = PdfWriter()
            for index in range(36):
                writer.add_page(source.pages[index % 2])
            writer.write(path)
            with patch("modules.ocr.ocr_page") as ocr:
                pages = read_document(path)
            self.assertEqual(len(pages), 36)
            self.assertEqual([page.page for page in pages], list(range(1, 37)))
            self.assertTrue(all(page.method == "pdf_text" for page in pages))
            self.assertIn("imaginary garden", pages[0].text)
            ocr.assert_not_called()

    def test_document_limits_remain_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "limit.pdf"
            make_text(path)
            with patch("modules.ocr.MAX_PDF_BYTES", 1):
                with self.assertRaisesRegex(DocumentError, "50MB"):
                    read_document(path)
            with patch("modules.ocr.MAX_PAGES", 1):
                with self.assertRaisesRegex(DocumentError, "100"):
                    read_document(path)
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            writer.encrypt("synthetic-test")
            writer.write(path)
            with self.assertRaisesRegex(DocumentError, "암호화"):
                read_document(path)

    def test_scan_and_annotation_never_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.pdf"
            writer = PdfWriter()
            writer.add_metadata({"/JudicialSDLC": SYNTHETIC_MARKER})
            writer.add_blank_page(width=300, height=300)
            writer.write(path)
            with patch("modules.ocr.assets.validate_models", side_effect=FileNotFoundError("models missing")):
                with self.assertRaises(OCRUnavailable):
                    read_document(path)
            make_text(Path(directory) / "text.pdf")
            writer = PdfWriter(clone_from=Path(directory) / "text.pdf")
            writer.pages[0][NameObject("/Annots")] = ArrayObject([DictionaryObject()])
            writer.write(path)
            with self.assertRaisesRegex(DocumentError, "주석"):
                read_document(path)

    def test_service_failures_are_not_no_hit(self):
        for mode in ("expired", "unavailable"):
            with self.subTest(mode=mode), running_server(mode) as (url, key, _events):
                connection = MockConnection(url, key)
                login(connection)
                with self.assertRaises(ServiceError):
                    search(connection, "DEMO-003")

    def test_external_endpoints_are_rejected(self):
        for url in (
            "https://example.com", "http://localhost:1234", "http://127.0.0.1:99/other",
            urlunsplit(("http", "demo-only:demo-only@127.0.0.1:99", "", "", "")),
            "http://127.0.0.1:99?x=y",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                MockConnection(url, "demo")

    def test_wrong_bootstrap_and_missing_login(self):
        with running_server() as (url, key, _events):
            with self.assertRaises(ServiceError):
                login(MockConnection(url, "wrong"))
            with self.assertRaises(ServiceError):
                search(MockConnection(url, key), "DEMO-001")

    def test_malformed_source_and_model_quote_rejected(self):
        connection = MockConnection("http://127.0.0.1:9999", "demo")
        with patch.object(connection, "post", return_value={"status": "found", "source": {"id": "wrong"}}):
            with self.assertRaises(ServiceError):
                search(connection, "DEMO-001")
        with patch.object(connection, "post", return_value={
            "status": "supported", "reason": "fake", "claim_quote": "wrong", "source_quote": "source",
        }):
            with self.assertRaises(ServiceError):
                compare_claim(connection, "DEMO-001", "claim", "source")


if __name__ == "__main__":
    unittest.main()
