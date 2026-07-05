# Claude-Web-Style Frontend Redesign — Design

## Context

`frontend/main.py` (275 lines) is a functional but minimal local-dev frontend: full-page-reload HTML forms, raw JSON/`<pre>` dumps of each sub-agent's output, and utilitarian styling. The backend pipeline (`app/agent.py`) is unchanged and out of scope here — this is a frontend-only redesign covering presentation and interaction, not agent behavior. The one exception: today the frontend renders every sub-agent's event text as it streams past (including the critic's own commentary and intermediate refiner passes); this redesign stops doing that and instead reads the four final documents (`budget_analysis`, `savings_strategy`, `debt_reduction`, `overall_picture`) directly from session state once the `critique_refine_loop` finishes, showing only the critic-approved (or best-available, see Edge Cases) picture.

Goal: make the local dev UI look and feel like Claude.ai's web app — same layout rhythm, calm typography, textbox placement — while presenting the analysis as readable prose instead of JSON.

## Architecture Decisions

**1. Interactivity model: SPA-lite (vanilla JS + `fetch()`), not full-page reloads.**
One HTML shell loads once. JS calls `/api/analyze`, `/api/resume`, `/api/resume-security` (JSON in, JSON out) and appends turns to a scrolling chat transcript — no page reload per turn. This mirrors the Kaggle course's own reference frontend (`Day5/expense-agent/submission_frontend/main.py`), which uses the identical pattern: FastAPI + hand-rolled HTML/CSS + vanilla JS `fetch()`, no React/Streamlit/Mesop. No new frontend framework or build step.

**2. Prose rendering: deterministic Python template, not an LLM "presenter" agent.**
A new pure module, `frontend/presenter.py`, walks the four already-critic-approved dicts and builds HTML directly (f-strings, no LLM call). This guarantees tone never drifts and numbers can never be mis-restated — the same reasoning that keeps `security_checkpoint`'s PII/injection filtering in deterministic regex rather than LLM instructions (see `app/agent.py`'s `scrub_pii`/`strip_injection_phrases`). Free, instant, and testable with plain `pytest`, matching this project's existing convention (pure functions → `tests/unit/`, LLM-dependent → `tests/smoke/`).

## Visual Design

**Shell**: single centered column, `max-width: 48rem`. Warm off-white background (`#faf9f7`). Font stack `ui-sans-serif, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif` (Claude's actual typeface is proprietary; this stack renders with the same clean, legible character cross-platform). Light theme only — this is a local dev tool, no dark-mode requirement.

**Empty state** (before the first message): vertically centered block —
- Heading: **"How can I help you today?"** (~1.75rem, medium weight)
- One muted sub-line describing what the agent does: looks at income, spending, debts, and savings goals; produces a full picture with a debt-payoff plan and savings strategy; accepts typed descriptions or uploaded statement PDFs.
- 3–4 clickable example-prompt chips (pill-shaped, light border) that prefill the textbox on click without auto-submitting.
- The input box sits directly below this block, vertically centered-ish — matching where Claude Web's box sits on its own empty state.

**After the first submit**: the heading/subtitle/chips disappear; the input box animates to a fixed bottom-of-viewport position; a scrollable transcript fills the space above it. Standard chat layout, matching Claude Web's transition on first message.

## Input Box & Upload UX

Rounded rectangle (`border-radius: 1.25rem`), subtle border, soft focus shadow, auto-growing `<textarea>`. Two controls in the same row, per the "Submit + parallel Upload Files button" requirement:
- **Upload Files** — paperclip-icon button, opens a native file picker (`accept="application/pdf" multiple"`). Selected files render as small removable chips above the input box before send.
- **Submit** — circular arrow-up button, right-aligned, disabled until there's text or at least one attached file.

## Chat Transcript

- **User turns**: light-gray rounded background box (Claude Web's actual treatment). Any attached files render as small file-icon chips inside the same turn.
- **Assistant turns**: no background, plain text, generous line-height, full column width.
- **Intake questions** (`intake_loop`'s existing HITL behavior, unchanged — only the presentation changes): rendered as an ordinary assistant turn — the question in plain prose, followed inline by a small textarea + "Skip remaining questions" checkbox + a "Reply" button, styled like a smaller version of the main input box.
- **Security checks** (`security_checkpoint`'s existing HITL behavior, unchanged): rendered as an ordinary assistant turn — the message in plain prose, followed by two calm, neutrally-styled buttons ("Continue", "Stop here"). No red/yellow alert styling — a security pause is routine, not alarming, per the calm-tone requirement.

Submitting an intake reply or a security choice appends a new user turn and continues the run in place — transcript grows, no reload.

## Output Rendering

Once `critique_refine_loop` completes (whether by `critic_verdict.approved == true` or by hitting `MAX_CRITIQUE_ROUNDS`), the backend reads `budget_analysis`, `savings_strategy`, `debt_reduction`, and `overall_picture` straight from session state and passes them to `frontend/presenter.py`, which renders two HTML sections. No JSON, no critic commentary, no intermediate refiner passes are ever shown.

**"Your Financial Picture"** (confirmation/analysis) — from `budget_analysis` + `overall_picture.wins`:
- Opening line stating income, total expenses, surplus, and savings rate in prose, with bolded numbers.
- Spending breakdown as a bullet list: **Category** — $amount (*percentage*% of expenses).
- The existing `spending_analysis` descriptive observations, one per line.
- A short "Where you're doing well" list sourced from `wins`.

**"Recommendations"** — from `savings_strategy` + `debt_reduction` + `overall_picture.next_steps`:
- Lead with `next_steps`, priority-ordered, as the main numbered action list (bolded amounts).
- *Savings & emergency fund* subsection: emergency fund target vs. current amount/status, then any remaining `savings_strategy.recommendations` not already reflected in `next_steps`, each with its rationale.
- *Debt payoff plan* subsection: each debt (name, balance, rate), then avalanche vs. snowball stated as prose with bolded months/interest figures, then `debt_reduction.recommendations`' descriptions/impacts as bullets — this is where the emergency-fund-parallel transparency note (added in the most recent Critic/`debt-reduction` fix) will surface to the user.
- Automation techniques, if present, as a short bullet list under savings.

Tone: calm, matter-of-fact, no exclamation points, no added enthusiasm beyond what the pipeline's own `acknowledgments`/`wins` already state — `presenter.py` only ever restates values that are already in the approved bundle, never invents framing.

## Edge Case: Critic Never Approves Within the Round Cap

If `critic_verdict.approved` is still `false` after `MAX_CRITIQUE_ROUNDS` (3) iterations (not observed in testing so far, but possible), show the last available bundle anyway through the same two-section rendering, prefaced with one calm line: *"This reflects the most recent draft; it didn't complete a final consistency check."* Withholding output entirely for a real, completed analysis run is worse UX than a rare, honestly-labeled caveat.

## API Contract

- `GET /` — serves the static shell (`frontend/static/index.html`) once.
- `POST /api/analyze` — multipart form (`message: str`, `documents: list[UploadFile]`). Creates a new session, runs the workflow, returns the JSON shape below.
- `POST /api/resume` — JSON body `{session_id, answer, skip_remaining}`. Resumes a paused intake interrupt.
- `POST /api/resume-security` — JSON body `{session_id, proceed}`. Resumes a paused security interrupt.

All three return one of:
```
{"type": "question", "session_id": str, "message": str}
{"type": "security", "session_id": str, "message": str}
{"type": "final", "session_id": str, "confirmation_html": str, "recommendations_html": str}
```
A `"final"` response ends that conversation. Sending another message afterward starts a brand-new session — this stays a one-shot analysis tool, not an open-ended follow-up chat (no requirement asked for post-analysis follow-up Q&A, and the backend `Workflow` itself terminates at `critique_refine_loop`).

## File Structure

- `frontend/main.py` — FastAPI app: the three `/api/*` routes plus static file serving. Thin glue only — session/runner plumbing and calls into `presenter.py`.
- `frontend/presenter.py` — new. Pure, deterministic functions rendering the two HTML sections from the four state dicts. No LLM call, no I/O.
- `frontend/static/index.html` — the page shell: empty-state markup, transcript container, input box markup. Plain static file, no template engine dependency.
- `frontend/static/style.css` — all styling.
- `frontend/static/app.js` — session-id tracking, `fetch()` calls, DOM rendering of transcript turns, file-chip and example-chip handling.

## Testing

- `tests/unit/test_presenter.py` (new, pytest) — feeds representative fixed dicts for all four documents (reusing shapes already established in `tests/smoke/test_critic_savings_debt_overlap_smoke.py`) and asserts: bolded numbers appear (`<strong>` around expected values), category names appear, both section headers appear, and no raw `{`/`}` JSON leaks into the output.
- Manual verification in a browser (per this project's UI-change convention): golden path (typed input, no documents), file-upload path, an intake-question round, a security-check trigger, and the max-critique-round fallback if it can be forced — before calling the work done.

## Scope Boundaries

- No changes to `app/agent.py`, any `skills/*.md`, or the intake/security HITL *behavior* — only how those interrupts are *displayed* changes.
- No dark mode, no multi-conversation history/sidebar, no follow-up chat after a final result — none of these were requested.
- No new Python dependencies — `fastapi`'s built-in `StaticFiles` covers static serving; file uploads already use `python-multipart` (already a dependency, per the existing `File`/`Form` usage).
