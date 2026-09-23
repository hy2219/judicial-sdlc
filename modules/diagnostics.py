"""Local error locations only: never persist exception messages or document data."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sys
import traceback


def diagnostic_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    else:
        base = Path.home() / ".local/state"
    if not base.is_absolute():
        raise OSError("A local absolute diagnostics directory is required.")
    identity = sys.executable if getattr(sys, "frozen", False) else str(Path(__file__).resolve().parents[1])
    app_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return base / "Judicial-SDLC" / app_id / "application.log"


def error_notice(exc_type, tb):
    kind = re.sub(r"[^A-Za-z0-9_]", "_", exc_type.__name__)[:80]
    frames = []
    for frame, line in traceback.walk_tb(tb):
        filename = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(frame.f_code.co_filename).name)[:100]
        function = re.sub(r"[^A-Za-z0-9_]", "_", frame.f_code.co_name)[:80]
        frames.append(f"{filename}:{line} {function}")
    text = f"{datetime.now(timezone.utc).isoformat()} {kind}\n" + "\n".join(frames[-20:]) + "\n"
    try:
        path = diagnostic_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size + len(text.encode("utf-8")) > 256 * 1024:
            path.replace(path.with_suffix(".previous.log"))
        with path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(text)
    except OSError:
        return f"오류 종류: {kind}\n로컬 진단 로그를 저장하지 못했습니다. 저장 공간·쓰기 권한을 확인하세요."
    return f"오류 종류: {kind}\n진단 로그: {path}\n로그에는 오류 종류와 코드 위치만 기록됩니다."


def show_startup_error(exc_type, exc, tb):
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc, tb)
        return
    notice = "프로그램을 시작하거나 실행하는 중 오류가 발생했습니다.\n" + error_notice(exc_type, tb)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, notice, "프로그램 오류", 0x10)
    else:
        import tkinter as tk
        from tkinter import messagebox
        try:
            messagebox.showerror("프로그램 오류", notice)
        except tk.TclError:
            if sys.stderr is not None:
                print(notice, file=sys.stderr)


def prepare_gui_runtime():
    # Windowed PyInstaller has no standard streams; libraries may still flush them.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    sys.excepthook = show_startup_error
