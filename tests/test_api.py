from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.knowledge import KnowledgeBase

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent


def test_healthcheck() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dialog_endpoint() -> None:
    started = client.post("/api/sessions", json={})
    assert started.status_code == 200
    session_id = started.json()["session_id"]

    response = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"text": "Каков порядок согласования документов?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["messages"] and "sources" in data


def test_knowledge_base_loading() -> None:
    kb = KnowledgeBase(ROOT / "kb" / "chunks.json")
    assert kb.chunks


def test_document_review_endpoint() -> None:
    response = client.post(
        "/api/documents/review",
        files={"file": ("draft.txt", "3.4. Срок согласования проекта документа.\n", "text/plain")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "reviewed"
    assert data["summary"]["sections"] == 1
    assert data["checks"][0]["source"]["point"] == "3.4"
