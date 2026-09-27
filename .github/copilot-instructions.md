# judicial-sdlc

Private local-document desktop template; synthetic-only data in GitHub/CI. Use
`.github/skills/compose-workflow/SKILL.md` and `docs/modules.rst` for composition.

- `modules/` holds reusable OCR, loopback mock lookup/SLM and HTTP functions.
- Python is the execution environment, not a scenario module.
- `app/` is a small generic GUI plus an editable pipeline. Put custom functions
  here; do not hardwire citation logic into common modules.
- No completed scenarios or `examples/` directory belong in the template.
  Write each scenario's composition, custom logic and UI from its approved
  requirements in a repository created from this template.
- Keep modules and app in one repository. No remote dependency repository or
  separate EXE per module. Distribute one fixed-folder installer.
- `tests/ocr_fixtures.py` and `tests/ocr_check.py` are neutral OCR source tests,
  not scenario applications and not part of the installed payload.
- OCR runtime dependencies live in `modules/ocr/requirements.txt`, aggregated
  by root `requirements.txt`; light text-only tests use
  `modules/ocr/requirements-text.txt`. Build dependencies live in
  `packaging/requirements.txt`.
- `packaging/` builds onedir plus a fixed-folder installer. Do not add
  `packaging/__init__.py`: it would shadow the third-party packaging library.
- `.github/scripts/` checks merged-source provenance and staged content; one Issue form is
  shown. `ISSUE_TEMPLATE/config.yml` configures the chooser, not a second form.

For a new request: native Issue assignment -> one main-target PR with ONLY plans/<issue>.json ->
STOP and wait for a human @copilot implementation request in that PR ->
implement in the SAME PR/branch -> human squash merge to main -> installer
Artifact linked on the Issue. No special prompt is needed at assignment.
Do not merge your own PR, create a second PR before the first is merged or start another agent task.
Keep the planning PR draft until implementation is submitted for CI; explain in the PR
that planning is ready for review but must not be merged yet.
After implementing the approved scope and acceptance tests, run Unit and targeted
regressions, then make the PR ready for review to trigger the full CI E2E.
Ready for review means submitted for CI, NOT acceptance passed. Report known failures
and pending checks; do not wait for an agent-side full E2E pass before submitting.
Scenario task edits: app/**/*.py,
tests/test_app.py and the approved plans/<issue>.json only. All common code,
packaging and dependencies require separate template maintenance.
Keep the approved plan JSON unchanged in implementation. If scope changes,
revise the plan first and wait for another human implementation request.
Do not claim ordinary comment approval is automatically verified by CI.
One active request per scenario repository; main records plan+implementation
as one squash commit. No task-start API, user token, automatic PR creation or
activation variable is part of this flow.

After an implementation is merged, a user-requested fix (including Fix with Copilot)
may use a new follow-up PR without a new Issue or plan. Reuse the unchanged plan
already in main; if exactly one plan exists it is selected automatically. With
multiple existing plans, add a standalone `Refs #N` line to the PR body selecting
the existing requirement Issue. Never overwrite or delete a merged plan.
Follow-up edits remain app/**/*.py and tests/test_app.py only; new scope requires
a new planned request and common maintenance remains separate. Do not silently
relax acceptance criteria: explain any proposed tolerance change for human review.
Human review, successful checks, squash merge and exact-source Windows acceptance
still apply; the result is posted on the original Issue. Sync trusted main changes
into the fix branch before final checks; do not alter shared code in the fix.

Never commit real documents/PDFs/images/accounts/credentials/internal endpoints,
weights or output. Never run generated installers/EXEs or alter security policies.
The installed app may read user-authorized ordinary PDFs locally; do not require
synthetic metadata or app-generated input for normal use. read_document defaults
to local PDFs up to 50MB/100 pages; synthetic_only=True is an explicit test mode.
Do not confuse real-document parsing with real precedent search/model inference:
lookup/SLM remain mocks. No actual document text may reach GitHub/Agent/CI/logs.
Windowed packaging must stay console-free. Retain modules.diagnostics.error_notice
in error handlers; do not replace it with traceback/console-only instructions
or log exception messages/document values. Startup initialization lives in run.py.
Use CPU CRAFT detection plus KLOCR recognition with verified local assets and no
runtime download. EasyOCR is detector-only; PageText.method is klocr for OCR.
OCR renders at 2.5x, at most 3,200,000 pixels and 2200 pixels per edge;
CRAFT canvas_size is 1536. Keep original-resolution KLOCR crops and source boxes.
Do not bypass these common limits, silently crop or skip rejected pages.
Use A4 595x842pt synthetic documents with at least 14pt body/footnote text.
Wrap and lay out text without enlarging paper or clipping content; assert every
page's dimensions. Test oversized-input rejection and recovery separately.
Preserve confidence_kind and warnings: token probabilities are not calibrated
accuracy. KLOCR weights are CC-BY-NC-SA-4.0; do not claim unrestricted commercial
use or redistribution. Keep bundled model-card/license attribution.
Mock comparison is not model inference. Preserve failures and OCR uncertainty.
Scenario-specific synthetic lookup records belong in app/, passed to
running_server(sources=...). Do not modify shared mocks for one scenario.
Login, endpoints and schemas are invented, not verified institutional APIs.
Keep no_hit, fixture_not_configured and service failures distinct. Custom source
sessions do not perform SLM comparison or RAG. Mock lookup must be opt-in for
synthetic demos; normal PDF extraction must not automatically call it.
Read the Skill's acceptance guidance: incomplete recognized records must not
silently disappear; original text/confidence must survive UI and JSON. Verify
requested source text is actually visible, not only stored in a report dict.
When identifiers can be wholly unreadable, include a digitless damaged-reference
case and a non-reference control in the approved acceptance plan. Preserve the
review candidate separately from raw page text; never invent an identifier.
Verify candidate visibility/export and no lookup for an unresolved identifier.
Preserve line, column and cell boundaries when extracting identifiers or context.
Never remove all whitespace before finding identifiers. Normalize only inside a
candidate whose boundaries are established. Preserve genuine wrapped identifiers,
but never append another row's serial number or another cell's text.
Use source spans and word/character geometry; a grouped OCR line or shared x
position alone does not establish a cell. Uncertain boundaries require a review
candidate, null lookup key and no lookup, not guessing or truncating a key.
Include wrapped-positive, cross-cell-negative and missing-geometry controls in
Unit and real short-PDF E2E acceptance. Implement business linking in app/;
do not claim generic table support or modify shared OCR to fit one fixture.
Keep RuntimeAcceptanceTests in tests/test_app.py for source E2E tests before
packaging; use actual app-generated inputs and OCR when requested.
Put all PDFium/Pillow/OCR-dependent tests in RuntimeAcceptanceTests, gated at
class level by JUDICIAL_RUNTIME_CHECKS=1. Lightweight tests must run with pypdf
alone. In CI, run runtime_check.py --phase unit, then --phase e2e in fresh processes.
Unit defers RuntimeAcceptanceTests and records successful app test IDs. E2E
excludes only those successes; skipped app cases in other classes still run.
Full E2E is owned by the PR CI `e2e` job after Ready for review, not by the agent.
During implementation or repairs, run Unit and only the targeted OCR/GUI regressions
needed for the change; do not repeatedly run the full E2E suite in the agent.
CI reruns Unit in its own E2E environment, then runs full E2E on the exact PR head.
Draft PRs defer E2E; a skipped check is not acceptance. New PR revisions cancel
obsolete CI runs. CI failure must remain failure; do not edit workflow gates or
weaken tests to get a green result. Pre-merge repairs stay on the same PR/branch.
Only latest successful `test`, `e2e` and `scope` checks permit human merge.
The installer controller also rejects a missing, skipped, pending or failed latest
`e2e` on the exact implementation head, even if someone merges it manually.
Windows source E2E remains required before packaging to catch platform differences.
The E2E stage requires the same source, test inventory and run context as Unit.
Do not reuse old Unit results after edits or another Actions job. E2E permits no
skipped or expected-failure cases. Keep .test-results/ local and ignored.
Use explicit UTF-8 for text file I/O. Agree bounded OCR acceptance inputs in
the plan; retain independent accuracy checks and separate long stress runs.
Emit newline-terminated test-start and periodic wait logs without document text.
Intercept GUI dialogs in unattended tests and fail on unexpected errors rather
than waiting for a person to dismiss a modal dialog.
Do not send generated PNG previews to model-facing image view or attachment tools.
Skip only this model image inspection, not PDF generation/rendering, actual OCR,
pixel/ink/text-layer/coordinate checks, GUI or export acceptance. Inspect their
results as text; do not skip tests or weaken thresholds. Human visual review
remains separate and must be reported as pending until actually performed.
This mitigates observed image-download failures; it does not establish their
service root cause or justify disabling PDF/image features in the application.
Use a task-specific app name for the window title and main heading, followed by
short user-facing instructions. Keep developer paths and code-editing instructions
in repository documentation, not the app UI. Keep the local-processing/no-upload
notice readable in the footer, not as the main heading.
Retain the generic extraction-first UI: show the untouched read_document PageText
snapshot in the "추출 원문" tab before custom results. Keep all read pages, original
whitespace/newlines and warnings even if custom processing filters or mutates its
input. Tab/page changes must not repeat OCR. Clear old source/results on new input
or read failure; after custom processing fails, raw input may remain visible but
processed-result saving must be disabled. Raw text is not a PDF image or accuracy
certification. Keep this view generic rather than adding citation/table logic.
Use Korean completion summaries, distinguish mocked versus actual checks, and
never claim PR body/Draft changes without verifying they persisted.

Run `python .github/scripts/runtime_check.py --phase unit` during implementation.
CI runs `python .github/scripts/runtime_check.py --phase e2e` after its own Unit
and model preparation. On headless Linux prefix both with `xvfb-run -a`.
Also run `python run.py --self-test`,
`python .github/scripts/check_public_content.py`. Source tests and build success
do not certify installation, runtime behavior, legal correctness or WDAC approval.
Original template only: one root commit after authorized maintenance. Fresh scenario
copies test the same common code; do not silently patch sample build infrastructure.
