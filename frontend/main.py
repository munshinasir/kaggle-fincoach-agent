"""Minimal web frontend for financial-coach-agent — local dev only.

A single text box where a user describes their financial situation in
natural language. Runs the agent locally via the ADK Runner (in-process —
no separate `agents-cli playground` server required) and renders each
sub-agent's output. Handles the intake/clarification loop's pauses: when
the workflow interrupts to ask a question, this renders the question and
resumes the same session with the user's answer. Run with:
`uv run uvicorn frontend.main:app --port 8080`
"""

import html
import json
import uuid

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.agent, which builds Gemini clients

from fastapi import FastAPI, File, Form, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import app as adk_app  # noqa: E402

fastapi_app = FastAPI(title="financial-coach-agent frontend")

_REQUEST_INPUT_FUNCTION_CALL_NAME = "adk_request_input"

_session_service = InMemorySessionService()
_runner = Runner(app=adk_app, session_service=_session_service)

# session_id -> {"interrupt_id": str, "message": str}, for sessions currently
# paused waiting on a clarifying answer. Local dev only — in-memory is fine.
_pending: dict[str, dict] = {}

_PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Financial Coach Agent</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; color: #1a1a1a; }
  h1 { font-size: 1.4rem; }
  textarea { width: 100%; height: 160px; font-family: inherit; font-size: 1rem; padding: 10px; box-sizing: border-box; }
  button { margin-top: 10px; padding: 10px 20px; font-size: 1rem; cursor: pointer; }
  .agent-block { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 16px 0; }
  .agent-block h2 { margin-top: 0; font-size: 1.05rem; }
  pre { white-space: pre-wrap; word-break: break-word; background: #f6f6f6; padding: 12px; border-radius: 6px; }
  .question-block { border: 1px solid #f0c040; background: #fffbea; border-radius: 8px; padding: 16px; margin: 16px 0; }
  .security-block { border: 1px solid #d9534f; background: #fdf2f2; border-radius: 8px; padding: 16px; margin: 16px 0; }
  label { display: block; margin-top: 10px; }
</style>
</head>
<body>
<h1>Financial Coach Agent</h1>
<p>Describe your income, expenses (or ask to fetch transactions), and any debts.</p>
"""

_FORM = """<form method="post" action="/analyze" enctype="multipart/form-data">
  <textarea name="message" placeholder="e.g. My monthly income is 5000, I have 2 dependants...">{prefill}</textarea><br>
  <label>Or upload statement documents (PDF): <input type="file" name="documents" accept="application/pdf" multiple></label><br>
  <button type="submit">Analyze</button>
</form>
"""

_QUESTION_FORM = """<div class="question-block">
  <h2>One quick question before I analyze this</h2>
  <p>{question}</p>
  <form method="post" action="/resume">
    <input type="hidden" name="session_id" value="{session_id}">
    <textarea name="answer" placeholder="Your answer..."></textarea>
    <label><input type="checkbox" name="skip_remaining" value="1"> Skip further questions, just analyze what I've given you</label>
    <button type="submit">Submit</button>
  </form>
</div>
"""

_SECURITY_FORM = """<div class="security-block">
  <h2>⚠ Security check</h2>
  <p>{message}</p>
  <form method="post" action="/resume-security">
    <input type="hidden" name="session_id" value="{session_id}">
    <button type="submit" name="proceed" value="1">Continue with cleaned version</button>
    <button type="submit" name="proceed" value="0">Stop here</button>
  </form>
</div>
"""

_FOOT = "</body></html>"


def _find_pending_question(events: list) -> dict | None:
    """Returns {"interrupt_id", "message", "kind"} if the run paused, else None.

    "kind" is "security" for the security_checkpoint's interrupt_id
    ("security_confirm") and "intake" for anything else (intake_loop's
    "intake_round_N" interrupt_ids) — see app/agent.py for both.
    """
    for event in reversed(events):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            fc = part.function_call
            if fc and fc.name == _REQUEST_INPUT_FUNCTION_CALL_NAME:
                kind = "security" if fc.id == "security_confirm" else "intake"
                return {"interrupt_id": fc.id, "message": (fc.args or {}).get("message", ""), "kind": kind}
    return None


def _render_results(message: str, events: list) -> str:
    blocks = []
    for event in events:
        found_text = False
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    blocks.append((event.author, part.text))
                    found_text = True
        if not found_text and isinstance(event.output, str) and event.output:
            blocks.append((event.author, event.output))

    results_html = ""
    for author, text in blocks:
        pretty = text
        try:
            pretty = json.dumps(json.loads(text), indent=2)
        except (json.JSONDecodeError, TypeError):
            pass
        results_html += (
            f'<div class="agent-block"><h2>{html.escape(author)}</h2>'
            f"<pre>{html.escape(pretty)}</pre></div>"
        )

    return (
        _PAGE_HEAD
        + _FORM.format(prefill=html.escape(message))
        + f"<h2>Results</h2>{results_html}"
        + _FOOT
    )


async def _run_turn(session_id: str, message_for_display: str, new_message: types.Content) -> str:
    events = [
        event
        async for event in _runner.run_async(
            user_id="web_user",
            session_id=session_id,
            new_message=new_message,
        )
    ]

    pending = _find_pending_question(events)
    if pending is not None:
        _pending[session_id] = pending
        if pending["kind"] == "security":
            return (
                _PAGE_HEAD
                + _SECURITY_FORM.format(message=html.escape(pending["message"]), session_id=session_id)
                + _FOOT
            )
        return (
            _PAGE_HEAD
            + _QUESTION_FORM.format(
                question=html.escape(pending["message"]),
                session_id=session_id,
            )
            + _FOOT
        )

    _pending.pop(session_id, None)
    return _render_results(message_for_display, events)


@fastapi_app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE_HEAD + _FORM.format(prefill="") + _FOOT


@fastapi_app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    message: str = Form(""),
    documents: list[UploadFile] = File(default=[]),
) -> str:
    session_id = str(uuid.uuid4())
    await _session_service.create_session(
        app_name="app", user_id="web_user", session_id=session_id
    )
    parts = []
    for doc in documents:
        if not doc.filename:
            continue
        data = await doc.read()
        if data:
            parts.append(types.Part.from_bytes(data=data, mime_type="application/pdf"))
    if message.strip():
        parts.append(types.Part.from_text(text=message))
    if not parts:
        parts.append(types.Part.from_text(text=""))
    new_message = types.Content(role="user", parts=parts)
    display_message = message if message.strip() else f"[{len(documents)} document(s) uploaded]"
    return await _run_turn(session_id, display_message, new_message)


@fastapi_app.post("/resume", response_class=HTMLResponse)
async def resume(
    session_id: str = Form(...),
    answer: str = Form(""),
    skip_remaining: str = Form(None),
) -> str:
    pending = _pending.get(session_id)
    if pending is None:
        return _PAGE_HEAD + "<p>No pending question for this session.</p>" + _FORM.format(prefill="") + _FOOT

    response_content = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=pending["interrupt_id"],
                    name=_REQUEST_INPUT_FUNCTION_CALL_NAME,
                    response={"answer": answer, "skip_remaining": bool(skip_remaining)},
                )
            )
        ],
    )
    return await _run_turn(session_id, answer, response_content)


@fastapi_app.post("/resume-security", response_class=HTMLResponse)
async def resume_security(
    session_id: str = Form(...),
    proceed: str = Form(...),
) -> str:
    pending = _pending.get(session_id)
    if pending is None:
        return _PAGE_HEAD + "<p>No pending question for this session.</p>" + _FORM.format(prefill="") + _FOOT

    response_content = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=pending["interrupt_id"],
                    name=_REQUEST_INPUT_FUNCTION_CALL_NAME,
                    response={"proceed": proceed == "1"},
                )
            )
        ],
    )
    return await _run_turn(session_id, "[security check response]", response_content)


app = fastapi_app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
