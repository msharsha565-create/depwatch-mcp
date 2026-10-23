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


def test_report_uses_provider_settings_from_environment(monkeypatch):
    from depwatch import cli

    seen = []

    async def fake_run(task, model, provider, base_url, api_key):
        seen.append((model, provider, base_url, api_key))
        return "the report"

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = TestClient(web.app)
    # openai provider without a model or key: off
    monkeypatch.setenv("DEPWATCH_PROVIDER", "openai")
    assert client.post("/api/report", json={"requirements": "x==1"}).status_code == 503
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("DEPWATCH_API_KEY_ENV", "GEMINI_API_KEY")
    assert client.post("/api/report", json={"requirements": "x==1"}).status_code == 503  # no model
    monkeypatch.setenv("DEPWATCH_MODEL", "gem")
    monkeypatch.setenv("DEPWATCH_BASE_URL", "http://x/v1")
    resp = client.post("/api/report", json={"requirements": "x==1"})
    assert resp.json() == {"report": "the report"}
    assert seen == [("gem", "openai", "http://x/v1", "gem-key")]
