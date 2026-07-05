"""Minimal web frontend for financial-coach-agent — local dev only.

A single text box where a user describes their financial situation in
natural language. Runs the agent locally via the ADK Runner (in-process —
no separate `agents-cli playground` server required) and renders each
sub-agent's output. Run with: `uv run uvicorn frontend.main:app --port 8080`
"""

import html
import json
import uuid

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.agent, which builds Gemini clients

from fastapi import FastAPI, Form  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import root_agent  # noqa: E402

app = FastAPI(title="financial-coach-agent frontend")

_session_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name="app", session_service=_session_service)

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
</style>
</head>
<body>
<h1>Financial Coach Agent</h1>
<p>Describe your income, expenses (or ask to fetch transactions), and any debts.</p>
"""

_FORM = """<form method="post" action="/analyze">
  <textarea name="message" placeholder="e.g. My monthly income is 5000, I have 2 dependants...">{prefill}</textarea><br>
  <button type="submit">Analyze</button>
</form>
"""

_FOOT = "</body></html>"


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE_HEAD + _FORM.format(prefill="") + _FOOT


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(message: str = Form(...)) -> str:
    session_id = str(uuid.uuid4())
    user_id = "web_user"
    await _session_service.create_session(
        app_name="app", user_id=user_id, session_id=session_id
    )

    blocks = []
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=message)]),
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.text:
                blocks.append((event.author, part.text))

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
