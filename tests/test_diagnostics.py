import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_log_excludes_exception_message_source_line_and_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs/application.log"
            try:
                raise ValueError("sensitive synthetic document / private/path.pdf")
            except ValueError as exc:
                with patch.object(diagnostics, "diagnostic_path", return_value=path):
                    notice = diagnostics.error_notice(type(exc), exc.__traceback__)
            text = path.read_text(encoding="utf-8")
            self.assertIn("ValueError", text)
            self.assertIn("test_diagnostics.py:", text)
            self.assertNotIn("sensitive", text)
            self.assertNotIn("private/path", text)
            self.assertNotIn("raise ValueError", text)
            self.assertIn(str(path), notice)
            self.assertNotIn("sensitive", notice)

    def test_log_is_bounded_and_write_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "application.log"
            path.write_text("x" * (256 * 1024), encoding="utf-8")
            with patch.object(diagnostics, "diagnostic_path", return_value=path):
                diagnostics.error_notice(RuntimeError, None)
            self.assertLess(path.stat().st_size, 1024)
            self.assertEqual(path.with_suffix(".previous.log").stat().st_size, 256 * 1024)
        with patch.object(diagnostics, "diagnostic_path", side_effect=PermissionError("private path")):
            notice = diagnostics.error_notice(ValueError, None)
        self.assertIn("저장하지 못했습니다", notice)
        self.assertNotIn("private path", notice)

    def test_log_lives_outside_installation_and_varies_by_app(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(diagnostics.sys, "platform", "win32"), \
                patch.dict(diagnostics.os.environ, {"LOCALAPPDATA": directory}), \
                patch.object(diagnostics.sys, "frozen", True, create=True):
            with patch.object(diagnostics.sys, "executable", "C:/Program Files/AppA/workflow-app.exe"):
                first = diagnostics.diagnostic_path()
            with patch.object(diagnostics.sys, "executable", "C:/Program Files/AppB/workflow-app.exe"):
                second = diagnostics.diagnostic_path()
            self.assertTrue(first.is_relative_to(Path(directory)))
            self.assertNotEqual(first, second)
            self.assertNotIn("Program Files", str(first))

    def test_windowless_streams_and_native_error_dialog(self):
        with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None), \
                patch.object(sys, "excepthook"), patch.object(diagnostics.sys, "platform", "win32"):
            diagnostics.prepare_gui_runtime()
            out, err = sys.stdout, sys.stderr
            try:
                out.write("synthetic output")
                err.flush()
                self.assertIs(sys.excepthook, diagnostics.show_startup_error)
                native = Mock()
                with patch.dict(sys.modules, {"ctypes": native}), \
                        patch.object(diagnostics, "error_notice", return_value="safe diagnostic path"):
                    sys.excepthook(RuntimeError, RuntimeError("not logged"), None)
                native.windll.user32.MessageBoxW.assert_called_once()
                self.assertNotIn("not logged", str(native.windll.user32.MessageBoxW.call_args))
            finally:
                out.close()
                err.close()

    def test_prepare_preserves_existing_streams_for_source_runs(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdout", out), patch.object(sys, "stderr", err), patch.object(sys, "excepthook"):
            diagnostics.prepare_gui_runtime()
            self.assertIs(sys.stdout, out)
            self.assertIs(sys.stderr, err)

    def test_unexpected_gui_error_clears_stale_result_without_console(self):
        from app.gui import Desktop
        screen = Mock()
        with patch("app.gui.error_notice", return_value="safe diagnostic"), \
                patch("app.gui.messagebox.showerror") as popup, \
                patch.object(sys, "stderr", None):
            Desktop.report_callback_exception(screen, RuntimeError, RuntimeError("sensitive"), None)
        screen.clear_result.assert_called_once()
        popup.assert_called_once()
        self.assertIn("safe diagnostic", popup.call_args.args[1])
        self.assertNotIn("콘솔", popup.call_args.args[1])

    def test_entrypoint_prepares_runtime_before_launching_gui(self):
        import run
        events = []
        with patch.object(sys, "argv", ["run.py"]), \
                patch("modules.diagnostics.prepare_gui_runtime", side_effect=lambda: events.append("prepare")), \
                patch("app.gui.launch", side_effect=lambda: events.append("launch")):
            run.main()
        self.assertEqual(events, ["prepare", "launch"])


if __name__ == "__main__":
    unittest.main()
