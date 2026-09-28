---
name: compose-workflow
description: >
  Compose the prepared OCR, mock precedent and mock SLM building blocks with
  custom Python logic in a small Windows desktop app. Use for a workflow Issue,
  a new processing step, or a UI change. Plan first, then implement in the same
  PR only after a human request; the human merges once at completion.
---

# Compose reusable building blocks

Explain choices in plain Korean. Read `README.md`, `docs/modules.rst`,
`app/pipeline.py` and only the relevant module. This is a private local-document
starter, not a real legal service. GitHub/CI use synthetic data only.
A = rules, B = retrieval, C = runtime AI draft.

## Where to work

- `app/gui.py`: small desktop shell, input selector, run button, JSON result view.
- `app/pipeline.py`: orchestration and the default `transform_pages` customization point.
- `modules/ocr`: real offline CRAFT detection/KLOCR recognition and text PDF reading.
- `modules/precedent`: demo login and lookup functions; only a loopback mock.
- `modules/slm`: demo claim-comparison function; canned response, not real inference.
- `modules/transport.py`: bounded loopback-only HTTP, no arbitrary remote endpoints.
- `modules/diagnostics.py`: console-free error notices and local privacy-safe logs.
- `tests/ocr_fixtures.py`: neutral synthetic OCR inputs, not a scenario or runtime component.
- Python is the execution environment bundled at build time, not an extra
  business module that every flow must call.

Scenario tasks may edit Python files in `app/`, `tests/test_app.py` and the
single approved `plans/<issue>.json`. Add ordinary functions under `app/` when
needed; do not build a plugin framework. Reuse common modules without changing
their contracts. The `.github`, `modules`, `mock_server`, `run.py`,
`packaging`, dependencies and shared tests are template-maintenance scope.
Do not change them just to make one scenario work.
Keep modules and the minimal app in this one repository. Do not add a dependency
repository, remote module loader or separate module executables.
There are no completed scenarios in the template. In a scenario repository
created from this template, write the approved composition and UI under `app/`
from its requirements; do not add an `examples/` directory to the template.

## Module calls

The following are real APIs, not proposed function names.

Read a generated synthetic PDF:

Generate neutral module-test input with
`python -m tests.ocr_fixtures --text local/synthetic.pdf`.

```python
from pathlib import Path
from modules.ocr import read_document

pages = read_document(Path("local/synthetic.pdf"))
```

`pages` contains `PageText(page, text, method, blocks, image_size, warnings)`.
Keep provenance and warnings when reshaping data. Image pages use real local
OCR; missing models or unreadable pages fail instead of inventing output.
OCR renders at 2.5x, at most 3,200,000 pixels and 2200 pixels per edge;
CRAFT canvas_size is 1536. Detection uses a bounded image, but EasyOCR returns
original-image coordinates and KLOCR reads original-resolution crops.
Do not bypass these common limits, silently crop or skip rejected pages.
Use A4 595x842pt synthetic documents with at least 14pt body/footnote text.
Wrap and lay out content without enlarging paper, clipping or shrinking text.
Assert dimensions of every generated page. Oversized inputs belong only in
separate rejection/recovery tests, never in the normal acceptance set.
These are input/compute bounds, not a guaranteed RAM ceiling or minimum PC spec.
Text-PDF line numbers and OCR grouped lines are app-derived, not printed lines.
Normal use accepts ordinary local PDFs without synthetic metadata, up to 50MB
and 100 pages. The `synthetic_only=True` option is for explicit development tests,
not a normal-file rejection rule. Build scenario parsers against realistic layout
and identifiers, not only the DEMO fixture strings. Keep unrecognized items visible
and make mock lookup limitations explicit. Never upload real document text or
files to GitHub, agent prompts, CI or logs; tests use independently invented data.

Reuse a local mock session for retrieval and comparison:

```python
from mock_server.server import running_server
from modules.transport import MockConnection
from modules.precedent import login, search
from modules.slm import compare_claim

with running_server() as (url, demo_key, events):
    connection = MockConnection(url, demo_key)
    login(connection)
    found = search(connection, "DEMO-001")
    if found["status"] == "found":
        result = compare_claim(
            connection,
            "DEMO-001",
            "DEMO-001: The workshop door is open on Monday.",
            found["source"]["text"],
        )
```

The mock starts and stops with this context manager; no separate service setup
or real password is needed. `no_hit`, `fixture_not_configured` and `ServiceError`
are different outcomes. Skip comparison without source. The SLM API is currently
a comparison-specific example, not a generic prompt/RAG endpoint. Unregistered
input produces an explicit unsupported/insufficient-basis response.

For a scenario's own synthetic identifiers, put a `sources` dict in `app/` and
pass it to `running_server(sources=sources)`. Each value contains nonempty
`title`, `text`, `location` strings, or is `None` for an explicit mock no-hit.
Missing keys mean `fixture_not_configured`, never a real nonexistent judgment.
The server supplies `id` and `authority="mock_fixture_only"`. Reuse the existing
`login`/`search` clients; do not bypass HTTP by reading fixture values in the UI.
Custom-source sessions return `insufficient_basis` for SLM comparison; they do
not implement RAG or model inference. See `docs/modules.rst`.
All login/API details are invented because institutional contracts are unknown.
Keep mock lookup off by default and enable it only for explicitly synthetic
demo input. Preserve ordinary local PDF reading without mock calls.

## Add custom logic between modules

Use small functions that accept one module's result and return the next input.
For example, insert this into `app/pipeline.py`:

```python
def select_pages(pages, keyword):
    return [page for page in pages if keyword in page.text]

def transform_pages(pages):
    return select_pages(pages, "교육")
```

Keep a synthetic case where the result is empty and explain what the screen
should show. The default workflow raises a visible error for no result.
Write task-specific extraction under `app/`, not in shared `modules/`.
Create scenario-specific synthetic inputs in `app/` or `tests/test_app.py`;
the common OCR fixtures are not a ready-made workflow.

Not every app needs every module. A formatting/calculation task needs no SLM
or mock server. The default app only reads/displays text until the user asks
for more. Adapt its result display in `app/gui.py` without imposing citation
columns on unrelated tasks.

Use a task-specific app name for the window title and main heading, followed by
short user-facing instructions. Developer paths and code-editing instructions
belong in repository documentation, not the app UI. Keep the local-processing/
no-upload notice readable in the footer rather than as the main heading.

Keep the template's extraction-first tabs when adapting the GUI. The raw tab uses
a snapshot of all pages returned by read_document before custom processing, not
the filtered/normalized report. Display its original text unchanged and show method,
PDF page and warnings separately. Never summarize or silently correct that view.
Keep no-hit pages and empty recognized text reviewable, without repeating OCR on
tab/page navigation. Processing errors must not enable result export; new input
or a reading error clears stale raw and processed data. The snapshot is a local
review view, not a guarantee of OCR accuracy or an original PDF rendering.

## One PR; plan first, human comment, implementation

The following sequence is for a new request, not a repair of an already merged
implementation. Keep the planning step for new scope.

1. Read the Issue's input, desired result, error cases and synthetic acceptance
   criteria. Ask one question at a time if unclear.
2. On native Issue assignment, create one draft PR targeting `main` with
   `plans/<issue>.json` as its only change. No special assignment prompt is needed.
   Describe the modules and custom functions, simple screen flow, failures and
   excluded scope. Complete the plan completeness checklist below before opening
   the PR. Link the Issue using `Refs`, not `Fixes`. Explain that the plan is
   ready to read but must not be merged. Stop without implementing.
3. The human reviews the plan and comments on this PR, for example:
   `@copilot 계획을 확인했습니다. 같은 PR에서 이 계획대로 구현해주세요.`
   A request to revise the plan is not implementation approval. Do not implement
   until the human explicitly requests it.
4. Continue on the SAME PR and branch. Keep the plan JSON unchanged and implement
   only the approved application scope. No second PR, task branch or agent task.
   If scope needs changing, revise the plan and stop for a new human decision.
5. Implement the acceptance tests, run Unit and targeted regressions, and make this
   PR ready for review to submit it to CI. Full E2E belongs to the CI `e2e` job;
   do not require an agent-side full-suite pass or claim pending checks passed.
   Report known failures. The human inspects the final code, plan and latest
   successful `test`, `e2e`, `scope`, then uses Squash and merge into main ONCE.
6. After main source CI, the build workflow verifies final scope and the actual
   human squash merge and successful PR-head E2E, builds that exact commit and posts the Artifact link on
   the Issue. Do not run generated EXEs or request manual SHA/build dispatch.

Do NOT merge PRs yourself. Ordinary plan-approval comments are a human/agent
process, NOT machine-verified approval records. CI does not prove that the plan
was approved before coding. Preserve the discussion and clearly request review.
GitHub-required workflow-run approvals remain human actions; never bypass them.
Process one request at a time in each scenario repository.

### Before merge: CI failures

Keep fixes on the same PR/branch and preserve the approved plan and thresholds.
Use Unit and targeted regressions to repair the failing path; CI owns full E2E.
Submit the updated PR as Ready for review even when reporting unresolved failures,
so CI can expose them as failed checks rather than an agent-only report.
Draft E2E skips are not passes. Do not merge or claim acceptance until the latest
`test`, `e2e` and `scope` checks succeed. A Fix with Copilot button, when offered
by GitHub for the failed check, is a repair entry point, not a guaranteed fix.
Do not create a second implementation PR or weaken tests to bypass a failure.

### After merge: follow-up fixes

A user-requested fix, including Fix with Copilot, may use a new PR for the already
merged task without adding another Issue or plan. Reuse the unchanged plan in
main. One existing plan is selected automatically; with multiple plans, put a
standalone `Refs #N` line in the PR body for the existing requirement Issue.
Do not overwrite/delete a merged plan or change shared modules, workflows,
packaging or dependencies. Stay within app/**/*.py and tests/test_app.py.
New scope still requires a new planned request. Explain acceptance-tolerance
changes for explicit human review; never quietly skip tests or weaken checks.
Sync trusted main updates before final checks. The human reviews the fix and
successful test/e2e/scope checks, then squash-merges. Windows acceptance and packaging
run for that exact merge; the artifact is linked on the original Issue.
Do not claim a repaired build was a first-pass instruction-only success.

## Plan completeness checklist

Use the actual Issue number in `plans/<issue>.json`; never copy a completed
scenario plan into the template or hardcode an example Issue number.
Include a top-level integer `issue` equal to that requirement Issue number.
Include these general fields in every new plan. Use "not applicable" with a
reason when an input or feature is outside the requested scope.

- `input_preparation`: for each requested input format, identify the synthetic
  content, its creator function/file, required markers and how the user obtains
  it (built-in input, button or command). If the user requests app-generated
  files, plan that generator and its UI, not just a file picker. Keep scenario
  generators in `app/`; test-only helpers may be in `tests/test_app.py`.
  Record page dimensions, font sizes, wrapping and OCR resource limits so the
  planned content fits the common module without changing it.
- `acceptance_cases`: connect each requirement to a concrete synthetic input,
  steps through the actual workflow and the expected visible/saved result.
  Include relevant empty, duplicate, missing-data and service-failure cases.
  List any requested filter's inclusion rules and review-state behavior.
- `module_compatibility`: read the existing module contracts and fixtures.
  A neutral module-test input is NOT a scenario end-to-end input. Check that
  synthetic identifiers/text can exercise the requested downstream branches.
  Unknown mock inputs must remain explicit unsupported/insufficient results.
- `change_scope`: list the required application files and explain how the
  generators, processing and UI fit the allowed scope without modifying shared
  modules, dependencies, workflows or packaging. Stop if common changes are needed.

Self-review the plan against the Issue before requesting approval: can a user
produce the promised input without supplying real data, and follow it through
to the promised output? Do not assume a shared fixture covers the scenario
because it is a valid file. Do not implement during this self-review.
For OCR inputs preserve uncertainty; never rewrite recognized text to force an
expected mock response. Generated PDFs/images/results remain local and untracked.
These are authoring instructions, not an automatic semantic approval gate;
a human must still review the plan.

## Validation and boundaries

### Fixed comparison and export conventions

Use instruction.md's conventions in the plan rather than proposing new tolerances.
These conventions do not relax identifier accuracy, candidate counts or CI gates.

- Context CER comparison only: normalize expected and actual U+0020, U+00A0,
  TAB, CR and LF runs to one U+0020, then trim boundary spaces. Keep all other
  characters unchanged. Do not delete all whitespace: a completely missing word
  separator remains an error. Compare each occurrence's sentence and before/after
  context separately using Levenshtein distance / normalized expected length,
  at most 10%. Expected null requires null; an empty normalized expected string
  requires an empty actual string. This is not parser, identifier-linking or
  line/cell-boundary normalization. Display and JSON retain original whitespace.
- Ink containment comparison only: use at most 2px outward expansion of each
  reported source box at the original 2.5x render (0.8pt), not display pixels or
  2pt/3pt. The union must contain all independent expected number ink on the
  correct page. Do not change displayed/exported boxes. Test adjacent-line
  intrusion with unexpanded boxes. Wrong pages/regions, missing number fragments,
  blank expected-ink regions and ink missing beyond 2px must fail. Add boundary
  and negative controls; this tolerance does not permit OCR character errors.
- Local JSON is a user-requested result, not a log: retain required source text,
  context, original whitespace, warnings and all records regardless of filters.
  Exclude document contents from logs, not required local JSON. Neither JSON nor
  logs contain credentials or absolute input paths. Do not send real documents
  or result JSON to GitHub/agents/Actions; use synthetic inputs for cloud tests.

For each acceptance case, cover all of **input -> retained records -> visible UI
-> exported data**, not just a successful module call. Apply these generic checks:

- Extraction must not silently discard an identifiable record because OCR dropped
  punctuation or spacing. Preserve incomplete/uncertain candidates for review,
  retaining the unmodified recognized text. Never normalize text to match mocks.
  Include a digitless damaged-reference case and a non-reference control when
  identifiers can be wholly unreadable. Keeping raw page text alone does not
  prove candidate retention: check the review list and exports separately, and
  ensure no lookup is performed for an unresolved identifier.
- Preserve the original page text, extraction method, page/image dimensions,
  block/word coordinates, confidence and warnings through composition and export.
  Match each displayed item to its source. If no items are extracted, surface that
  explicitly rather than claiming a complete result.
- A field present in a dict is NOT proof it is visible to the user. Exercise
  selection/detail display with long source text; verify required original text,
  reasons and warnings are readable. Give user-facing statuses Korean labels.
- Save with the filter still active and verify all intended records and provenance
  remain in JSON. Exercise confirmation changes, input switches, errors and retry.
- Missing punctuation, several records on one line, duplicates and OCR-altered
  text need deterministic regression cases independent of a particular OCR run.
- Preserve line, column and cell boundaries before identifying or linking records.
  Never remove all whitespace before finding identifiers. Normalize only within
  an established candidate, preserving original spans and line breaks separately.
  A genuine wrapped identifier needs layout and semantic continuity; shared x
  position or an OCR-grouped line alone is not enough. Do not append another
  row's serial number or borrow dates/context from a different cell.
  Ambiguous joins require retained fragments/locations/reasons, null lookup key
  and no lookup. Do not infer a shorter key from a concatenated value or match
  identifiers against a fixture list to repair them.
  Plan wrapped-positive, cross-cell-negative and missing-geometry controls, plus
  a clear non-reference record with unrelated citation words in another cell.
  Use independent geometry in Unit tests and short app-generated text/scan PDFs
  in E2E; observe actual lookup keys and retained UI/exports. Keep the normal
  acceptance counts unchanged. Put business linking in app/ using existing
  PDFium characters or original OCR words/boxes. General table extraction is
  separate scope, not implied by protecting identifier boundaries.

Keep `RuntimeAcceptanceTests` in `tests/test_app.py` and replace its generic shell
case with real end-to-end source cases for this requested app. Gate the class with
`JUDICIAL_RUNTIME_CHECKS=1` so the lightweight `test` job does not need OCR/models.
PR CI's `e2e` job and the Windows build both run
`.github/scripts/runtime_check.py --phase unit` followed by `--phase e2e` with
verified models prepared before E2E. Unit records successful app test IDs and
defers the named E2E class. E2E excludes only Unit successes; skipped app cases
in other classes still run. The two stages must cover the entire app inventory
without repeating passed tests. E2E permits no skip or expected failure.
The local Unit record must match source, test IDs and run context; rerun Unit
after edits, missing results or a different Actions job. Never commit .test-results/.
Put every PDFium/Pillow/OCR-dependent test in the gated
RuntimeAcceptanceTests class; lightweight tests must run with pypdf alone.
Do not add a skip in another class to hide a missing lightweight dependency.
For requested OCR input, generate the app's own scan and mixed PDFs, call actual
`read_document` and then the actual pipeline/UI/export. Do not mock recognition,
document reading, extraction or comparison to make this acceptance path pass.
OS dialogs may be substituted only to supply temporary paths without user input.
For generated PDFs, a successful write and same-library text extraction are not
enough. Use the existing PDFium dependency to independently open/render every
generated page, verify it is nonblank and check text-layer content where expected.
Do not send generated PNG previews to model-facing image view or attachment tools.
Skip only this model image inspection, not PDF generation/rendering, actual OCR,
pixel/ink/text-layer/coordinate checks, GUI or export acceptance. Inspect their
results as text; do not skip tests or weaken thresholds. Human visual review
remains separate and must be reported as pending until actually performed.
This mitigates observed image-download failures; it does not establish their
service root cause or justify disabling PDF/image features in the application.
When constructing pypdf page streams, use `page.replace_contents(stream)` so the
content stream is registered as an indirect PDF object; do not assign a raw
stream directly to `/Contents`. Preserve the synthetic metadata marker.
Assert expected record coverage and original provenance, not exact mock status
for OCR text that genuinely differs. Do not import `tests/` from application code.
This runtime check is still source execution, NOT installed Windows EXE validation.

Specify UTF-8 on text file I/O. Bound representative OCR page counts in the
approved plan instead of repeatedly running long stress documents in every
build; do not reduce agreed accuracy or hide skipped cases. Distinguish the
small source acceptance from separate long-document and installed-app checks.
Print newline-terminated starts and periodic elapsed-time messages without
document values. A wait message proves the test loop is alive, not page progress.
Intercept unattended GUI error dialogs, record unexpected calls as failures,
and explicitly assert expected-error cases so modal dialogs cannot hang CI.
Exercise the oversized OCR error through the GUI, prohibit complete-result export
after failure, then process a supported A4 input to verify recovery. Never count
partial pages as a successful whole document.

The default-branch `copilot-setup-steps.yml` prepares pinned CPU OCR dependencies,
verified local models, Korean fonts and Xvfb before each Cloud Agent session.
Its common OCR check is not a scenario acceptance result. Inspect setup failures
before proceeding: GitHub may still start the agent after a setup step fails.
If preparation failed, report the exact missing prerequisite and request operator
maintenance; do not bypass network controls or silently change dependency versions.
On the headless Linux agent, run
`xvfb-run -a python .github/scripts/runtime_check.py --phase unit` and targeted
regressions needed for the current change. Full E2E is not an agent completion
requirement: the Ready-for-review PR CI runs its own Unit followed by
`xvfb-run -a python .github/scripts/runtime_check.py --phase e2e`.
Each invocation creates its own display; do not assume a setup display persists.
Keep scenario runtime acceptance out of environment setup so unfinished scenario
code does not prevent preparation of the environment needed to fix it.

Before completion, write the PR summary and user-facing progress in Korean.
Replace stale "plan only / not implemented" descriptions. State which checks were
actually run, which were mocked, and which could not run. If you cannot edit the
PR body or change Draft status, say so; do not claim success without read-back.
Ask for human final review and never merge your own PR.

```text
python .github/scripts/runtime_check.py --phase unit
python run.py --self-test
python .github/scripts/check_public_content.py
# Full suite in CI after its own Unit, dependencies and model preparation:
python .github/scripts/runtime_check.py --phase e2e
```

Lightweight dependencies: `modules/ocr/requirements-text.txt`. All runtime
dependencies: root `requirements.txt`, which references the OCR module's
requirements. Build-only dependencies: `packaging/requirements.txt`.
Preflight examines staged/tracked files; generated PDFs, weights and outputs
stay local and ignored. Do not claim this is complete DLP.

OCR changes are common maintenance: CPU-only, verified local models and
`download_enabled=False`. Preparation uses `python modules/ocr/prepare.py`;
the offline source check is `python -m tests.ocr_check`.
OCR PageText.method is `klocr`. Words retain source boxes, generation warnings and
`confidence_kind`; the token probability score is uncalibrated, not known accuracy.
Never restore EasyOCR recognition as a hidden fallback. The detector is CRAFT, not
the full PaddleDet KLOCR package. Pinned weights/tokenizer/configuration are local
in `assets/klocr`; no runtime download or remote model code is allowed.
KLOCR weights use CC-BY-NC-SA-4.0. Preserve licensing notices and require rights
review before deployment/redistribution; do not describe the weights as Apache.
No real PDFs in GitHub/CI, account data, internal URLs, browser cookies, external
service fallbacks or runtime model downloads. User-authorized real PDFs stay local.
Never correct OCR text just to match a fixture.

The app is built windowed, without a console. Preserve the default error-notice
path: `modules.diagnostics.error_notice(type(exc), exc.__traceback__)` in handled
GUI errors and `report_callback_exception`. It logs only error class/code locations,
not exception messages or user data. Do not tell users to inspect a console.
Exercise the source GUI with stdout/stderr unavailable after runtime preparation;
do not launch a generated EXE to test this.

The installer includes Python/OCR in a fixed folder. Do not execute the generated EXE
or Setup locally or in CI, alter security policies or remove an existing Python/OCR.
No final static-analysis gate, email, automatic release or third approval.
Do not promise WDAC acceptance.

The original template main retains one root commit through separately approved
maintenance. Scenario repository main accumulates one squash commit per completed
request (plan plus implementation). Scenario samples test the same common
infrastructure without custom packaging patches. Do not delete branches
automatically or claim secure erasure.
