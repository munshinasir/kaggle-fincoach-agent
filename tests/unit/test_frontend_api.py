"""Unit tests for frontend/main.py's non-LLM-dependent routes. Anything that
runs the actual Workflow (a real Gemini call) belongs in
tests/smoke/test_frontend_api_smoke.py instead, per this project's testing
conventions (AGENTS.md).
"""

from starlette.testclient import TestClient

from frontend.main import app

client = TestClient(app)


def test_index_serves_the_static_shell():
    response = client.get("/")
    assert response.status_code == 200
    assert "How can I help you today?" in response.text


def test_resume_without_a_pending_session_returns_409():
    response = client.post("/api/resume", json={"session_id": "nonexistent", "answer": "hi"})
    assert response.status_code == 409
    assert response.json()["type"] == "error"


def test_resume_security_without_a_pending_session_returns_409():
    response = client.post("/api/resume-security", json={"session_id": "nonexistent", "proceed": True})
    assert response.status_code == 409
    assert response.json()["type"] == "error"
