"""FastAPI backend for the Claude-Web-style financial-coach-agent frontend.

Serves a static SPA shell (frontend/static/) and a small JSON API that
drives it. Runs the agent locally via the ADK Runner (in-process — no
separate `agents-cli playground` server required). See
docs/superpowers/specs/2026-07-05-claude-web-style-frontend-design.md for
the full design this implements.

Run with: `uv run uvicorn frontend.main:app --port 8080`
"""

import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.agent, which builds Gemini clients

from fastapi import FastAPI, File, Form, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import app as adk_app  # noqa: E402
from frontend.presenter import assemble_final_bundle, render_final  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

fastapi_app = FastAPI(title="financial-coach-agent frontend")
fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_REQUEST_INPUT_FUNCTION_CALL_NAME = "adk_request_input"

_session_service = InMemorySessionService()
_runner = Runner(app=adk_app, session_service=_session_service)

# session_id -> interrupt_id, for sessions currently paused waiting on a
# clarifying or security answer. Local dev only — in-memory is fine.
_pending: dict[str, str] = {}


def _find_pending_interrupt(events: list) -> tuple[str, str] | None:
    """Returns (interrupt_id, message) for the paused interrupt, if any."""
    for event in reversed(events):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            fc = part.function_call
            if fc and fc.name == _REQUEST_INPUT_FUNCTION_CALL_NAME:
                return fc.id, (fc.args or {}).get("message", "")
    return None


async def _run_turn(session_id: str, new_message: types.Content) -> dict:
    events = [
        event
        async for event in _runner.run_async(
            user_id="web_user",
            session_id=session_id,
            new_message=new_message,
        )
    ]

    pending = _find_pending_interrupt(events)
    if pending is not None:
        interrupt_id, message = pending
        _pending[session_id] = interrupt_id
        kind = "security" if interrupt_id == "security_confirm" else "question"
        return {"type": kind, "session_id": session_id, "message": message}

    _pending.pop(session_id, None)
    session = await _session_service.get_session(
        app_name="app", user_id="web_user", session_id=session_id
    )
    bundle = assemble_final_bundle(session.state)
    approved = bool((session.state.get("critic_verdict") or {}).get("approved", False))
    rendered = render_final(bundle, approved=approved)
    return {"type": "final", "session_id": session_id, **rendered}


@fastapi_app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@fastapi_app.post("/api/analyze")
async def analyze(
    message: str = Form(""),
    documents: list[UploadFile] = File(default=[]),
) -> JSONResponse:
    session_id = str(uuid.uuid4())
    await _session_service.create_session(app_name="app", user_id="web_user", session_id=session_id)

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
    return JSONResponse(await _run_turn(session_id, new_message))


@fastapi_app.post("/api/resume")
async def resume(payload: dict) -> JSONResponse:
    session_id = payload["session_id"]
    interrupt_id = _pending.get(session_id)
    if interrupt_id is None:
        return JSONResponse(
            {"type": "error", "message": "No pending question for this session."},
            status_code=409,
        )

    response_content = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=_REQUEST_INPUT_FUNCTION_CALL_NAME,
                    response={
                        "answer": payload.get("answer", ""),
                        "skip_remaining": bool(payload.get("skip_remaining", False)),
                    },
                )
            )
        ],
    )
    return JSONResponse(await _run_turn(session_id, response_content))


@fastapi_app.post("/api/resume-security")
async def resume_security(payload: dict) -> JSONResponse:
    session_id = payload["session_id"]
    interrupt_id = _pending.get(session_id)
    if interrupt_id is None:
        return JSONResponse(
            {"type": "error", "message": "No pending question for this session."},
            status_code=409,
        )

    response_content = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=_REQUEST_INPUT_FUNCTION_CALL_NAME,
                    response={"proceed": bool(payload.get("proceed", False))},
                )
            )
        ],
    )
    return JSONResponse(await _run_turn(session_id, response_content))


app = fastapi_app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
