from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillTests(unittest.TestCase):
    def test_app_copy_separates_user_titles_from_developer_and_privacy_guidance(self):
        guide = (ROOT / "instruction.md").read_text(encoding="utf-8")
        self.assertIn("창 제목과 화면 상단", guide)
        self.assertIn("개발 안내는 저장소 문서에만", guide)
        self.assertIn("작은 하단 안내", guide)
        for filename in (".github/copilot-instructions.md",
                         ".github/skills/compose-workflow/SKILL.md"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("task-specific app name", text)
            self.assertIn("footer", text)

    def test_identifier_boundary_guidance_requires_positive_negative_and_ambiguous_cases(self):
        guide = (ROOT / "instruction.md").read_text(encoding="utf-8")
        for phrase in (
            "줄·열·셀 경계", "하나의 번호 내부", "공백·탭·줄바꿈을 먼저 지운 뒤",
            "같은 x좌표만으로는 충분하지", "검색 키 null, 조회 0회",
            "2095나345678", "2097다123456401", "관리번호", "후보 0개·조회 0회",
            "text/scan", "실제 HTTP", "정상 입력 건수에는 섞지 않습니다",
        ):
            self.assertIn(phrase, guide)
        for filename in (".github/copilot-instructions.md",
                         ".github/skills/compose-workflow/SKILL.md"):
            text = " ".join((ROOT / filename).read_text(encoding="utf-8").split())
            for phrase in ("line, column and cell boundaries",
                           "Never remove all whitespace before finding identifiers.",
                           "wrapped-positive, cross-cell-negative and missing-geometry",
                           "null lookup key and no lookup", "app/"):
                self.assertIn(phrase, text, filename)

    def test_follow_up_guidance_keeps_initial_plan_and_reuses_existing_request(self):
        for filename in ("README.md", "instruction.md", "docs/workflow.rst",
                         ".github/copilot-instructions.md",
                         ".github/skills/compose-workflow/SKILL.md"):
            content = (ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(file=filename):
                self.assertIn("Fix with Copilot", content)
                self.assertIn("Refs #N", content)
        instructions = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
        self.assertIn("For a new request:", instructions)
        self.assertIn("Never overwrite or delete a merged plan", instructions)

    def test_authoring_guidance_keeps_resource_limits_and_runtime_collection(self):
        guide = (ROOT / "instruction.md").read_text(encoding="utf-8")
        for phrase in ("595×842pt", "840×1080pt", "320만 픽셀", "2200픽셀", "1536",
                       "14pt", "한도 초과", "--phase unit", "--phase e2e"):
            self.assertIn(phrase, guide)
        for filename in (".github/copilot-instructions.md",
                         ".github/skills/compose-workflow/SKILL.md"):
            text = " ".join((ROOT / filename).read_text(encoding="utf-8").split())
            for phrase in ("595x842pt", "3,200,000", "2200", "canvas_size is 1536",
                           "pypdf alone", "RuntimeAcceptanceTests"):
                self.assertIn(phrase, text, filename)

    def test_unit_e2e_instructions_cover_deduplication_and_skipped_cases(self):
        for filename in ("README.md", "instruction.md", "docs/release.rst",
                         "docs/workflow.rst", ".github/copilot-instructions.md",
                         ".github/skills/compose-workflow/SKILL.md"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            for phrase in ("--phase unit", "--phase e2e", "E2E", "skip"):
                self.assertIn(phrase, text, filename)
        self.assertIn(".test-results/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_walkthrough_requires_digitless_reference_and_negative_control(self):
        guide = (ROOT / "instruction.md").read_text(encoding="utf-8")
        for phrase in (
            "대법원 □□□ 판결을 인용한다.",
            "확인 필요 후보 1개, 검색 키 null, 조회 0회",
            "이 문서는 판결문 작성 방법을 설명한다.",
            "인용 후보 0개", "실제 GUI·저장 결과",
            "원문 페이지에 문장이 남았다는 것만으로",
        ):
            self.assertIn(phrase, guide)
        for filename in (".github/copilot-instructions.md",
                         ".github/skills/compose-workflow/SKILL.md"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("digitless damaged-reference", text)
            self.assertIn("non-reference control", text)

    def test_png_preview_policy_preserves_real_acceptance(self):
        for filename in (".github/copilot-instructions.md",
                         ".github/skills/compose-workflow/SKILL.md"):
            content = (ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(file=filename):
                self.assertIn(
                    "Do not send generated PNG previews to model-facing image view or attachment tools.",
                    content,
                )
                self.assertIn("not PDF generation/rendering, actual OCR", content)
                self.assertIn("pixel/ink/text-layer/coordinate checks, GUI or export acceptance", content)
                self.assertIn("do not skip tests or weaken thresholds", content)
                self.assertIn("Human visual review", content)
        guide = (ROOT / "instruction.md").read_text(encoding="utf-8")
        self.assertIn("모델의 이미지 view/첨부 도구로 전달하는 단계만 생략", guide)
        self.assertIn("PDF 생성·렌더링·실제 OCR·픽셀/잉크/텍스트층/좌표 검사·GUI·저장 시험은 모두 유지", guide)
        self.assertIn("시험 skip이나 정확도 기준 완화는 허용하지 않습니다.", guide)
        self.assertIn("수행 전에는 미확인으로 보고", guide)

    def test_citation_walkthrough_matches_supported_mock_contract(self):
        guide = (ROOT / "instruction.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        modules = (ROOT / "docs/modules.rst").read_text(encoding="utf-8")
        skill = (ROOT / ".github/skills/compose-workflow/SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "Use this template", "Private", "Assignees", "같은 PR",
            "Squash and merge", "Artifact", "running_server(sources=...)",
            "fixture_not_configured", "실제 방식을 확인하지 못해",
            "encoding=\"utf-8\"", "30초", "5쪽", "53쪽", "Windows",
        ):
            self.assertIn(phrase, guide)
        for text in (guide, readme, modules, skill):
            self.assertIn("running_server(sources=", text)
        self.assertIn("SLM / RAG", guide)
        self.assertIn("실제 모델 추론·RAG 검색 없음", guide)
        self.assertIn("기본 꺼짐", guide)
        self.assertIn("app/**/*.py", guide)
        self.assertNotIn("판례검색·SLM·mock 원문 비교·외부 API는 호출하지 않습니다.", guide)
        self.assertNotIn("증거목록 시나리오 따라 하기", readme)

    def test_cloud_agent_skill_metadata_and_referenced_modules(self):
        skill = ROOT / ".github/skills/compose-workflow/SKILL.md"
        content = skill.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nname: compose-workflow\n"))
        self.assertIn("\ndescription:", content.split("---", 2)[1])
        self.assertNotIn("allowed-tools:", content)
        self.assertIn("Stop without implementing.", content)
        self.assertIn("One PR; plan first, human comment, implementation", content)
        self.assertIn("SAME PR and branch", content)
        self.assertIn("Do NOT merge", content)
        self.assertIn("CPU-only", content)
        self.assertIn("Do not execute the generated EXE", content)
        self.assertIn("def transform_pages(pages)", content)
        self.assertIn("from modules.precedent import login, search", content)
        self.assertIn("from modules.slm import compare_claim", content)
        self.assertIn("from modules.ocr import read_document", content)
        self.assertIn("There are no completed scenarios in the template.", content)
        self.assertIn("write the approved composition and UI", content)
        for filename in (
            "run.py", "app/pipeline.py", "modules/ocr/__init__.py",
            "modules/precedent/__init__.py", "modules/slm/__init__.py", "docs/modules.rst",
        ):
            self.assertTrue((ROOT / filename).is_file(), filename)

    def test_only_one_user_facing_issue_form(self):
        directory = ROOT / ".github/ISSUE_TEMPLATE"
        self.assertEqual(
            sorted(path.name for path in directory.glob("*.yml") if path.name != "config.yml"),
            ["workflow-request.yml"],
        )

    def test_planning_covers_input_preparation_and_end_to_end_acceptance(self):
        skill = (ROOT / ".github/skills/compose-workflow/SKILL.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs/workflow.rst").read_text(encoding="utf-8")
        form = (ROOT / ".github/ISSUE_TEMPLATE/workflow-request.yml").read_text(encoding="utf-8")
        for field in ("input_preparation", "acceptance_cases", "module_compatibility", "change_scope"):
            with self.subTest(field=field):
                self.assertIn(field, skill)
                self.assertIn(field, guide)
        self.assertIn("plans/<issue>.json", skill)
        self.assertNotIn("plans/1.json", skill)
        self.assertIn("NOT a scenario end-to-end input", skill)
        self.assertIn("not an automatic semantic approval gate", skill)
        self.assertIn("plan that generator and its UI", skill)
        self.assertIn("입력을 준비하는 방법", form)
        self.assertIn("공통 OCR 시험 PDF", guide)

    def test_native_assignment_has_no_external_task_prerequisites(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        instructions = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
        form = (ROOT / ".github/ISSUE_TEMPLATE/workflow-request.yml").read_text(encoding="utf-8")
        self.assertIn("Optional prompt는 비워도 됩니다", readme)
        self.assertIn("No special prompt is needed at assignment", instructions)
        self.assertIn("같은 PR", form)
        for path in (ROOT / ".github").rglob("*"):
            if path.suffix in {".py", ".yml", ".md"}:
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("COPILOT_WORKFLOW_TOKEN", text, str(path))
                self.assertNotIn("WORKFLOW_AUTOMATION_ENABLED", text, str(path))

    def test_acceptance_instructions_cover_observed_runtime_gaps(self):
        skill = (ROOT / ".github/skills/compose-workflow/SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "input -> retained records -> visible UI", "punctuation or spacing",
            "confidence and warnings", "NOT proof it is visible", "filter still active",
            "RuntimeAcceptanceTests", "Do not mock recognition", "Korean",
            "do not claim success without read-back",
            "independently open/render every", "page.replace_contents(stream)",
        ):
            self.assertIn(phrase, skill)

    def test_local_real_pdf_is_not_confused_with_cloud_test_data(self):
        skill = (ROOT / ".github/skills/compose-workflow/SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        privacy = (ROOT / "docs/privacy.rst").read_text(encoding="utf-8")
        self.assertIn("ordinary local PDFs without synthetic metadata", skill)
        self.assertIn("No real PDFs in GitHub/CI", skill)
        self.assertIn("--windowed", readme)
        self.assertIn("50MB·100페이지", readme)
        self.assertIn("예외 메시지·본문·변수 값·입력 경로", privacy)

    def test_raw_extraction_view_is_kept_separate_from_custom_results(self):
        skill = (ROOT / ".github/skills/compose-workflow/SKILL.md").read_text(encoding="utf-8")
        instructions = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
        self.assertIn("snapshot of all pages returned by read_document", skill)
        self.assertIn("original text unchanged", skill)
        self.assertIn("without repeating OCR", skill)
        self.assertIn("Tab/page changes must not repeat OCR", instructions)


if __name__ == "__main__":
    unittest.main()
