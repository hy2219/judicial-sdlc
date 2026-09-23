"""Generic local desktop shell: select a PDF, call the workflow, show/save output."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.pipeline import demo_pages, run_pipeline
from modules.diagnostics import error_notice
from modules.ocr import DocumentError, read_document
from modules.transport import ServiceError


APP_TITLE = "PDF 문서 읽기"


def user_document_directory():
    documents = Path.home() / "Documents"
    return str(documents if documents.is_dir() else Path.home())


class Desktop(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x650")
        self.minsize(640, 440)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.input_path = None
        self.report = None
        self.raw_pages = ()
        self.task_kind = None
        self.status = tk.StringVar(value="내장 가상 글자로 시작할 수 있습니다.")
        self.input_name = tk.StringVar(value="내장 가상 글자")
        self.raw_page_label = tk.StringVar()
        self.raw_info = tk.StringVar(value="PDF를 읽으면 페이지별 추출 원문이 표시됩니다.")
        self.controls = []
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        self.privacy_notice = ttk.Label(
            frame, text="문서는 이 PC에서 처리합니다. 실제 자료는 GitHub에 업로드하지 마세요.",
            font="TkSmallCaptionFont", wraplength=580,
        )
        self.privacy_notice.pack(side="bottom", anchor="w", pady=(8, 0))
        self.heading = ttk.Label(frame, text=APP_TITLE, font=("", 15, "bold"))
        self.heading.pack(anchor="w")
        ttk.Label(frame, text="PDF를 선택하고 실행하면 추출된 내용을 확인하고 저장할 수 있습니다.",
                  wraplength=580).pack(anchor="w", pady=8)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        for text, command in [
            ("내장 예제", self.use_builtin), ("PDF 선택", self.choose_pdf), ("실행", self.start),
        ]:
            button = ttk.Button(buttons, text=text, command=command)
            button.pack(side="left", padx=(0, 8))
            self.controls.append(button)
        ttk.Label(frame, textvariable=self.input_name, wraplength=780).pack(anchor="w", pady=8)
        ttk.Label(frame, textvariable=self.status, wraplength=780).pack(anchor="w")
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill="both", expand=True, pady=12)
        self.raw_tab = ttk.Frame(self.tabs, padding=8)
        output_frame = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.raw_tab, text="1. 추출 원문")
        self.tabs.add(output_frame, text="2. 처리 결과")
        ttk.Label(
            self.raw_tab,
            text="PDF 읽기/OCR 결과 그대로입니다. 요약·자동 교정·업무별 선별 전 내용이며, 원본 PDF의 화면이나 정확성 인증은 아닙니다.",
            wraplength=780,
        ).pack(anchor="w")
        navigation = ttk.Frame(self.raw_tab)
        navigation.pack(fill="x", pady=6)
        self.raw_previous = ttk.Button(navigation, text="이전 쪽", command=lambda: self.move_raw_page(-1),
                                       state="disabled")
        self.raw_previous.pack(side="left")
        self.raw_selector = ttk.Combobox(navigation, textvariable=self.raw_page_label,
                                         state="disabled", width=24)
        self.raw_selector.pack(side="left", padx=8)
        self.raw_selector.bind("<<ComboboxSelected>>", self.show_raw_page)
        self.raw_next = ttk.Button(navigation, text="다음 쪽", command=lambda: self.move_raw_page(1),
                                   state="disabled")
        self.raw_next.pack(side="left")
        ttk.Label(self.raw_tab, textvariable=self.raw_info, wraplength=780).pack(anchor="w")
        self.raw_warnings = self.text_area(self.raw_tab, wrap="word", height=3, expand=False)
        self.raw_output = self.text_area(self.raw_tab, wrap="none", height=12, horizontal=True)
        ttk.Label(output_frame, text="업무별 처리 결과입니다. 입력으로 읽은 내용은 ‘추출 원문’ 탭에서 확인하세요.",
                  wraplength=780).pack(anchor="w")
        self.output = tk.Text(output_frame, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        self.output.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.save_button = ttk.Button(frame, text="결과 JSON 저장", command=self.save, state="disabled")
        self.save_button.pack(anchor="w")
        self.protocol("WM_DELETE_WINDOW", self.close)

    @staticmethod
    def text_area(parent, *, wrap, height, horizontal=False, expand=True):
        frame = ttk.Frame(parent)
        frame.pack(fill="both" if expand else "x", expand=expand, pady=4)
        text = tk.Text(frame, wrap=wrap, height=height, state="disabled")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vertical.set)
        text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        if horizontal:
            scroll = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
            text.configure(xscrollcommand=scroll.set)
            scroll.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        return text

    @staticmethod
    def replace_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        widget.yview_moveto(0)
        widget.xview_moveto(0)

    def show_raw_page(self, event=None):
        index = self.raw_selector.current()
        if not 0 <= index < len(self.raw_pages):
            return
        page = self.raw_pages[index]
        method = {"pdf_text": "텍스트 직접 읽기", "klocr": "KLOCR 이미지 인식"}.get(page.method, page.method)
        label = f"PDF {page.page}쪽" if self.input_path else "내장 가상 글자 (PDF 아님)"
        empty = " · 읽힌 텍스트 없음" if not page.text else ""
        self.raw_info.set(f"{label} · {method} · {len(page.text)}자{empty} · 표시 번호는 인쇄 쪽번호가 아닙니다.")
        warnings = list(page.warnings)
        for block in page.blocks:
            warnings.extend(block.get("warnings", ()))
        self.replace_text(self.raw_warnings, "\n".join(dict.fromkeys(warnings)) if warnings else
                          "추출 경고 없음 — 내용의 정확성을 보장하지 않습니다.")
        self.replace_text(self.raw_output, page.text)
        self.raw_previous.configure(state="normal" if index > 0 else "disabled")
        self.raw_next.configure(state="normal" if index + 1 < len(self.raw_pages) else "disabled")

    def move_raw_page(self, offset):
        index = self.raw_selector.current() + offset
        if 0 <= index < len(self.raw_pages):
            self.raw_selector.current(index)
            self.show_raw_page()

    def set_output(self, text):
        self.replace_text(self.output, text)

    def clear_result(self):
        self.report = None
        self.set_output("")
        self.save_button.configure(state="disabled")
        self.raw_pages = ()
        self.raw_selector.configure(values=(), state="disabled")
        self.raw_page_label.set("")
        self.raw_info.set("PDF를 읽으면 페이지별 추출 원문이 표시됩니다.")
        self.replace_text(self.raw_output, "")
        self.replace_text(self.raw_warnings, "")
        self.raw_previous.configure(state="disabled")
        self.raw_next.configure(state="disabled")
        self.tabs.select(self.raw_tab)

    def use_builtin(self):
        self.clear_result()
        self.input_path = None
        self.input_name.set("내장 가상 글자")
        self.status.set("입력을 변경했습니다. 실행을 눌러주세요.")

    def choose_pdf(self):
        filename = filedialog.askopenfilename(
            title="로컬에서 처리할 PDF 선택",
            initialdir=user_document_directory(), filetypes=[("PDF", "*.pdf")],
        )
        if filename:
            self.clear_result()
            self.input_path = Path(filename)
            self.input_name.set(self.input_path.name)
            self.status.set("로컬 PDF를 선택했습니다. 실행을 눌러주세요. 원문·결과를 GitHub에 올리지 마세요.")

    def start(self):
        if self.future is not None:
            return
        self.clear_result()
        for control in self.controls:
            control.configure(state="disabled")
        path = self.input_path
        self.status.set("자료 읽기·OCR 중...")
        self.task_kind = "read"
        self.future = self.executor.submit(read_document, path) if path else self.executor.submit(demo_pages)
        self.after(50, self.poll)

    def poll(self):
        if not self.future.done():
            self.after(50, self.poll)
            return
        completed, self.future = self.future, None
        try:
            result = completed.result()
            if self.task_kind == "read":
                if not result:
                    raise DocumentError("읽은 페이지가 없습니다.")
                # Snapshot before custom processing can mutate nested OCR blocks.
                self.raw_pages = tuple(deepcopy(result))
                self.raw_selector.configure(
                    values=[f"PDF {page.page}쪽 ({index + 1}/{len(result)})" if self.input_path
                            else f"내장 가상 글자 ({index + 1}/{len(result)})"
                            for index, page in enumerate(result)],
                    state="readonly",
                )
                self.raw_selector.current(0)
                self.show_raw_page()
                self.tabs.select(self.raw_tab)
                self.status.set("추출 원문을 확인할 수 있습니다. 업무 처리 중...")
                self.task_kind = "process"
                self.future = self.executor.submit(run_pipeline, result)
                self.after(50, self.poll)
                return
            rendered = json.dumps(result, ensure_ascii=False, indent=2)
        except (DocumentError, ServiceError, OSError, ValueError, TypeError) as exc:
            if self.task_kind == "read":
                self.clear_result()
            else:
                self.report = None
                self.set_output("")
                self.save_button.configure(state="disabled")
            self.status.set(f"처리 중단: {exc}")
            for control in self.controls:
                control.configure(state="normal")
            messagebox.showerror("처리 중단", f"{exc}\n\n{error_notice(type(exc), exc.__traceback__)}", parent=self)
            return
        for control in self.controls:
            control.configure(state="normal")
        self.report = result
        self.set_output(rendered)
        self.save_button.configure(state="normal")
        self.status.set("처리 완료. ‘추출 원문’을 먼저 확인한 뒤 ‘처리 결과’를 열어주세요.")

    def save(self):
        if self.report is None:
            return
        filename = filedialog.asksaveasfilename(
            title="새 결과 파일", initialdir=user_document_directory(),
            initialfile="workflow-result.json", defaultextension=".json", filetypes=[("JSON", "*.json")],
        )
        if filename:
            try:
                with Path(filename).open("x", encoding="utf-8") as output:
                    json.dump(self.report, output, ensure_ascii=False, indent=2)
            except OSError as exc:
                messagebox.showerror("저장 실패", f"기존 파일은 덮어쓰지 않습니다.\n{exc}\n\n"
                                     + error_notice(type(exc), exc.__traceback__), parent=self)
                return
            self.status.set("결과를 로컬에 저장했습니다. 저장소에는 올리지 마세요.")

    def report_callback_exception(self, exc_type, exc, tb):
        self.clear_result()
        self.status.set("예상하지 못한 오류로 중단했습니다.")
        messagebox.showerror("프로그램 오류", "이전 결과는 사용할 수 없습니다.\n\n"
                             + error_notice(exc_type, tb), parent=self)

    def close(self):
        if self.future is not None:
            messagebox.showinfo("처리 중", "현재 작업이 끝난 뒤 종료해주세요.")
            return
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def launch():
    Desktop().mainloop()
