from starlette.testclient import TestClient

from depwatch import web


def test_index_served():
    resp = TestClient(web.app).get("/")
    assert resp.status_code == 200
    assert "depwatch" in resp.text


def test_audit_rejects_empty_input():
    resp = TestClient(web.app).post("/api/audit", json={"requirements": "  "})
    assert resp.status_code == 400


def test_audit_returns_flags(monkeypatch):
    async def fake(client, text):
        return {"packages": [{"name": "x", "flags": ["OUTDATED"]}], "needs_attention": 1}

    monkeypatch.setattr("depwatch.audit.audit_requirements", fake)
    resp = TestClient(web.app).post("/api/audit", json={"requirements": "x==1"})
    assert resp.json()["needs_attention"] == 1


def test_report_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = TestClient(web.app).post("/api/report", json={"requirements": "x==1"})
    assert resp.status_code == 503


def test_malformed_and_oversized_bodies_return_400():
    client = TestClient(web.app)
    assert client.post("/api/audit", content=b"not json").status_code == 400
    assert client.post("/api/audit", json=["a"]).status_code == 400
    too_many = "\n".join(f"pkg{i}==1" for i in range(300))
    assert client.post("/api/audit", json={"requirements": too_many}).status_code == 400
