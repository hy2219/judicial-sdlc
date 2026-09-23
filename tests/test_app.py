"""Tests for the small, editable default application, not a fixed legal workflow."""

import ast
import gc
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from app.pipeline import demo_pages, run_pipeline
from modules.ocr import DocumentError, PageText

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def test_default_workflow_displays_pages_without_service_calls(self):
        with patch("modules.precedent.login") as login, patch("modules.slm.compare_claim") as compare:
            result = run_pipeline(demo_pages())
        self.assertTrue(result["local_only"])
        self.assertEqual(len(result["pages"]), 1)
        self.assertIn("업무 로직", result["pages"][0]["text"])
        login.assert_not_called()
        compare.assert_not_called()

    def test_custom_step_is_called_and_can_change_output(self):
        page = PageText(1, "SYNTHETIC original")
        with patch("app.pipeline.transform_pages", return_value=[PageText(1, "CUSTOM result")]) as custom:
            report = run_pipeline([page])
        custom.assert_called_once_with([page])
        self.assertEqual(report["pages"][0]["text"], "CUSTOM result")
        self.assertEqual(page.text, "SYNTHETIC original")

    def test_empty_custom_result_is_explicit_failure(self):
        with patch("app.pipeline.transform_pages", return_value=[]):
            with self.assertRaises(DocumentError):
                run_pipeline(demo_pages())

    def test_provenance_and_warnings_survive_default_transform(self):
        page = PageText(2, "synthetic", "klocr", (
            {"text": "synthetic", "box": [[0, 0], [5, 0], [5, 5], [0, 5]], "confidence": 0.4},
        ), (10, 10), ("Review OCR.",))
        report = json.loads(json.dumps(run_pipeline([page])))
        output = report["pages"][0]
        self.assertEqual(output["page"], 2)
        self.assertEqual(output["warnings"], ["Review OCR."])
        self.assertEqual(output["blocks"][0]["confidence"], 0.4)

    def test_default_app_does_not_import_scenario_or_test_code(self):
        for path in (ROOT / "app").glob("*.py"):
            nodes = ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            for node in nodes:
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
                    [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
                )
                for name in names:
                    self.assertFalse(name.split(".")[0] in {"examples", "tests"}, str(path))
                    self.assertNotEqual(name, "modules.citations")

    def test_template_has_no_scenario_or_remote_module_loader(self):
        self.assertFalse((ROOT / "examples").exists())
        self.assertFalse((ROOT / "dependencies.lock.json").exists())
        self.assertFalse((ROOT / "packaging/dependencies.py").exists())

    def test_cli_self_test_is_generic_and_headless(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "run.py"), "--self-test"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
        self.assertIn("workflow hook", result.stdout)

    def test_shared_modules_do_not_import_application_or_example(self):
        for path in (ROOT / "modules").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    name = node.module or ""
                    self.assertFalse(name == "app" or name.startswith(("app.", "examples.")), str(path))

    def make_screen(self):
        # Release earlier test windows on the Tk thread before starting a worker.
        gc.collect()
        logs = tempfile.TemporaryDirectory()
        self.addCleanup(logs.cleanup)
        diagnostic_path = patch("modules.diagnostics.diagnostic_path",
                                return_value=Path(logs.name) / "application.log")
        diagnostic_path.start()
        self.addCleanup(diagnostic_path.stop)
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest("Tkinter is not installed in this source-test environment.")
        from app.gui import Desktop

        try:
            screen = Desktop()
        except tk.TclError as exc:
            self.skipTest(f"GUI display unavailable: {exc}")
        screen.withdraw()
        self.addCleanup(self.close_screen, screen)
        return screen

    @staticmethod
    def close_screen(screen):
        screen.close()
        gc.collect()

    def finish_screen(self, screen):
        deadline = time.monotonic() + 5
        while screen.future is not None and time.monotonic() < deadline:
            screen.update()
            time.sleep(0.01)
        self.assertIsNone(screen.future, "Source workflow did not finish.")

    def check_user_facing_header(self, screen):
        from tkinter import ttk
        screen.deiconify()
        screen.update()
        self.assertEqual(screen.title(), "PDF 문서 읽기")
        self.assertEqual(screen.heading.cget("text"), screen.title())
        self.assertIn("GitHub에 업로드하지 마세요", screen.privacy_notice.cget("text"))
        self.assertEqual(screen.privacy_notice.pack_info()["side"], "bottom")
        labels = [widget.cget("text") for widget in screen.heading.master.winfo_children()
                  if isinstance(widget, ttk.Label)]
        self.assertIn("PDF를 선택하고 실행하면 추출된 내용을 확인하고 저장할 수 있습니다.", labels)
        self.assertFalse(any("modules/" in text or "app/pipeline.py" in text for text in labels))
        for size in ("900x650", "640x440"):
            screen.geometry(size)
            screen.update()
            self.assertLess(screen.heading.winfo_rooty(), screen.privacy_notice.winfo_rooty())
            self.assertLessEqual(screen.privacy_notice.winfo_rooty() + screen.privacy_notice.winfo_height(),
                                 screen.winfo_rooty() + screen.winfo_height())
        screen.geometry("900x650")
        screen.withdraw()

    def test_source_gui_result_save_error_and_recovery(self):
        screen = self.make_screen()
        self.check_user_facing_header(screen)
        finish = lambda: self.finish_screen(screen)
        screen.start()
        finish()
        self.assertIn("pages", screen.report)
        self.assertEqual(screen.tabs.select(), str(screen.raw_tab))
        self.assertEqual(screen.raw_output.get("1.0", "end-1c"), demo_pages()[0].text)
        expected = json.loads(json.dumps(screen.report))
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "report.json"
            with patch("app.gui.filedialog.asksaveasfilename", return_value=str(saved)):
                screen.save()
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), expected)
            with patch("app.gui.filedialog.asksaveasfilename", return_value=str(saved)), \
                    patch("app.gui.messagebox.showerror") as error:
                screen.save()
            error.assert_called_once()
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), expected)

        with patch("app.gui.run_pipeline", side_effect=DocumentError("Synthetic failure")), \
                patch("app.gui.messagebox.showerror") as error:
            screen.start()
            finish()
        error.assert_called_once()
        self.assertIsNone(screen.report)
        self.assertEqual(screen.output.get("1.0", "end").strip(), "")
        self.assertEqual(screen.raw_output.get("1.0", "end-1c"), demo_pages()[0].text)
        self.assertEqual(str(screen.save_button["state"]), "disabled")

        screen.start()
        finish()
        self.assertIsNotNone(screen.report)
        screen.use_builtin()
        self.assertIsNone(screen.report)
        self.assertEqual(screen.raw_pages, ())
        self.assertEqual(screen.raw_output.get("1.0", "end-1c"), "")
        self.assertEqual(str(screen.raw_selector["state"]), "disabled")

        from pypdf import PdfReader, PdfWriter
        from tests.ocr_fixtures import make_text
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "generated.pdf"
            path = Path(directory) / "ordinary.pdf"
            make_text(generated)
            writer = PdfWriter()
            for page in PdfReader(generated).pages:
                writer.add_page(page)
            writer.write(path)
            with patch("app.gui.filedialog.askopenfilename", return_value=str(path)):
                screen.choose_pdf()
            with patch("app.gui.messagebox.showerror") as error:
                screen.start()
                finish()
            error.assert_not_called()
            self.assertEqual(len(screen.report["pages"]), 2)
            self.assertTrue(screen.report["local_only"])
            self.assertEqual(len(screen.raw_pages), 2)
            screen.move_raw_page(1)
            self.assertEqual(screen.raw_output.get("1.0", "end-1c"), screen.raw_pages[1].text)
            self.assertEqual(str(screen.raw_next["state"]), "disabled")
            screen.move_raw_page(-1)
            self.assertEqual(screen.raw_selector.current(), 0)
            with patch("app.gui.read_document", side_effect=DocumentError("Synthetic read failure")), \
                    patch("app.gui.messagebox.showerror") as error:
                screen.start()
                finish()
            error.assert_called_once()
            self.assertEqual(screen.raw_pages, ())
            self.assertEqual(screen.raw_output.get("1.0", "end-1c"), "")
            self.assertEqual(str(screen.save_button["state"]), "disabled")
        self.check_raw_text_snapshot(screen)

    def check_raw_text_snapshot(self, screen):
        text = "  가상 원문\t첫 줄\n\n오인식도  그대로\n" + "긴 문장 " * 200 + "\n마지막 줄\n"
        warning = "원문 대조 필요"
        pages = [
            PageText(1, text, "klocr", ({"text": "원문", "warnings": [warning]},),
                     (100, 100), (warning,)),
            PageText(2, "", warnings=("글자 없음",)),
            PageText(3, "인용 없는 가상 첨부 내용"),
        ]
        started, release = Event(), Event()

        def transform(values):
            values[0].blocks[0]["text"] = "CHANGED"
            values[0].blocks[0]["warnings"].clear()
            started.set()
            if not release.wait(5):
                raise RuntimeError("Synthetic test did not release custom processing")
            return [PageText(1, "가상 처리 결과")]

        with patch("app.gui.read_document", return_value=pages) as read, \
                patch("app.pipeline.transform_pages", side_effect=transform):
            screen.input_path = Path("synthetic.pdf")
            screen.start()
            try:
                deadline = time.monotonic() + 5
                while not started.is_set() and time.monotonic() < deadline:
                    screen.update()
                    time.sleep(0.01)
                self.assertTrue(started.is_set())
                self.assertIsNone(screen.report)
                self.assertEqual(str(screen.save_button["state"]), "disabled")
                self.assertEqual(screen.tabs.select(), str(screen.raw_tab))
                self.assertEqual(screen.raw_output.get("1.0", "end-1c"), text)
                self.assertEqual(str(screen.raw_output["state"]), "disabled")
                self.assertEqual(str(screen.raw_output["wrap"]), "none")
                self.assertEqual(screen.raw_warnings.get("1.0", "end-1c"), warning)
                self.assertEqual(screen.raw_pages[0].blocks[0]["text"], "원문")
                self.assertEqual(screen.raw_pages[0].blocks[0]["warnings"], [warning])
                screen.raw_output.yview_moveto(1)
                screen.raw_output.xview_moveto(1)
                screen.update()
                self.assertAlmostEqual(screen.raw_output.yview()[1], 1.0, places=2)
                self.assertAlmostEqual(screen.raw_output.xview()[1], 1.0, places=2)
                screen.move_raw_page(1)
                self.assertEqual(screen.raw_output.get("1.0", "end-1c"), "")
                self.assertIn("읽힌 텍스트 없음", screen.raw_info.get())
                self.assertEqual(screen.raw_warnings.get("1.0", "end-1c"), "글자 없음")
                screen.move_raw_page(1)
                self.assertEqual(screen.raw_output.get("1.0", "end-1c"), pages[2].text)
            finally:
                release.set()
                self.finish_screen(screen)
        read.assert_called_once_with(Path("synthetic.pdf"))
        self.assertEqual(screen.report["pages"][0]["text"], "가상 처리 결과")
        self.assertEqual(len(screen.raw_pages), 3)
        screen.raw_selector.current(0)
        screen.show_raw_page()
        self.assertEqual(screen.raw_output.get("1.0", "end-1c"), text)
        self.assertEqual(str(screen.raw_previous["state"]), "disabled")
        self.assertIn("가상 처리 결과", screen.output.get("1.0", "end-1c"))


@unittest.skipUnless(os.environ.get("JUDICIAL_RUNTIME_CHECKS") == "1", "Full dependencies/models run before packaging.")
class RuntimeAcceptanceTests(unittest.TestCase):
    def test_real_document_to_report(self):
        from modules.ocr import read_document
        from tests.ocr_fixtures import make_scan

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.pdf"
            make_scan(path, mixed=True)
            with patch.object(socket.socket, "connect", side_effect=RuntimeError("Network blocked during OCR")), \
                    patch.object(socket.socket, "connect_ex", side_effect=RuntimeError("Network blocked during OCR")), \
                    patch.object(socket, "create_connection", side_effect=RuntimeError("Network blocked during OCR")):
                pages = read_document(path)
            self.assertEqual([page.method for page in pages], ["pdf_text", "klocr"])
            report = json.loads(json.dumps(run_pipeline(pages)))
            self.assertEqual(len(report["pages"]), 2)
            for page, saved in zip(pages, report["pages"]):
                self.assertEqual(saved["text"], page.text)
                self.assertEqual(saved["method"], page.method)
            self.assertTrue(report["pages"][1]["blocks"])
            self.assertIn("confidence", report["pages"][1]["blocks"][0])


if __name__ == "__main__":
    unittest.main()
