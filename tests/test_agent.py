from types import SimpleNamespace as NS

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from depwatch.agent import run_agent
from depwatch.server import mcp


def open_session():
    # A context manager rather than a fixture: anyio cancel scopes must exit in the entering task.
    return create_connected_server_and_client_session(mcp._mcp_server)


class FakeClient:
    """Scripted stand-in for AsyncAnthropic: yields one canned response per call."""

    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs["messages"][:])
        return next(self._responses)


REQ = "requests==2.19.0\n"


def tool_use(id_):
    block = NS(type="tool_use", id=id_, name="audit_requirements",
               input={"requirements_txt": REQ})
    return NS(content=[block])


def text(t):
    return NS(content=[NS(type="text", text=t)])


async def test_server_exposes_tools():
    async with open_session() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    assert names == {"get_package_info", "audit_requirements"}


async def test_agent_feeds_tool_results_back(monkeypatch):
    async def fake_audit(client, text_):
        return {"packages": [{"name": "requests", "flags": ["OUTDATED"]}], "needs_attention": 1}

    monkeypatch.setattr("depwatch.audit.audit_requirements", fake_audit)
    client = FakeClient([tool_use("t1"), text("requests is outdated")])
    async with open_session() as session:
        answer = await run_agent("audit", session, client)
    assert answer == "requests is outdated"
    result = client.calls[1][-1]["content"][0]
    assert result["tool_use_id"] == "t1"
    assert "OUTDATED" in result["content"]


async def test_agent_gives_up_after_max_rounds(monkeypatch):
    async def fake_audit(client, text_):
        return {"packages": [], "needs_attention": 0}

    monkeypatch.setattr("depwatch.audit.audit_requirements", fake_audit)
    client = FakeClient([tool_use(f"t{i}") for i in range(3)])
    async with open_session() as session:
        with pytest.raises(RuntimeError):
            await run_agent("x", session, client, max_rounds=3)
