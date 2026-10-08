from app.api import create_app
from app.graph import RouteDecision, build_graph
from app.workflow import build_workflow
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver


def client(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-secret")
    team = build_graph(
        router=lambda s: RouteDecision(
            next_agent="researcher" if not s.get("visited") else "finish", reason="test"
        ),
        writer=lambda role, question, evidence: evidence,
    )
    workflow = build_workflow(checkpointer=InMemorySaver(), team_graph=team)
    return TestClient(create_app(workflow=workflow))


def test_chat_and_metrics(monkeypatch):
    with client(monkeypatch) as api:
        assert api.get("/health").status_code == 200
        assert (
            api.post(
                "/chat", json={"thread_id": "a", "message": "¿Qué base guarda pedidos?"}
            ).status_code
            == 401
        )
        headers = {"X-API-Key": "test-secret"}
        answer = api.post(
            "/chat",
            headers=headers,
            json={"thread_id": "a", "message": "¿Qué base guarda pedidos?"},
        ).json()
        assert answer["status"] == "completed"
        assert "PostgreSQL" in answer["answer"]
        assert "agent_http_requests_total" in api.get("/metrics", headers=headers).text


def test_approval_resume_and_rejection(monkeypatch):
    with client(monkeypatch) as api:
        headers = {"X-API-Key": "test-secret"}
        pending = api.post(
            "/chat",
            headers=headers,
            json={"thread_id": "b", "message": "Publicar informe de PostgreSQL"},
        ).json()
        assert pending["status"] == "pending"
        assert (
            api.post(
                "/chat", headers=headers, json={"thread_id": "b", "message": "otra"}
            ).status_code
            == 409
        )
        approved = api.post(
            "/approve", headers=headers, json={"thread_id": "b", "approved": True}
        ).json()
        assert approved["status"] == "completed"
        pending = api.post(
            "/chat", headers=headers, json={"thread_id": "c", "message": "Borrar datos"}
        ).json()
        assert pending["status"] == "pending"
        rejected = api.post(
            "/approve", headers=headers, json={"thread_id": "c", "approved": False}
        ).json()
        assert rejected["status"] == "rejected"
