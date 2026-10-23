import json
from types import SimpleNamespace as NS

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from depwatch import agent as agent_module
from depwatch.agent import OpenAICompatChat, run_agent, run_agent_openai
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


# --- OpenAI-compatible backend -------------------------------------------------------------

def audit_call(call_id, extra=None):
    call = {"id": call_id, "type": "function",
            "function": {"name": "audit_requirements",
                         "arguments": json.dumps({"requirements_txt": "requests==2.19.0\n"})}}
    if extra:
        call["extra_content"] = extra
    return {"role": "assistant", "content": None, "tool_calls": [call]}


class ScriptedChat:
    def __init__(self, replies):
        self._replies = iter(replies)
        self.seen = []

    async def complete(self, messages, tools):
        self.seen.append((json.loads(json.dumps(messages)), tools))
        return next(self._replies)


@pytest.fixture
def fake_audit(monkeypatch):
    async def fake(client, text):
        return {"packages": [{"name": "requests", "flags": ["OUTDATED"]}], "needs_attention": 1}

    monkeypatch.setattr("depwatch.audit.audit_requirements", fake)


async def test_openai_agent_feeds_tool_results_back_and_echoes_metadata(fake_audit):
    sig = {"google": {"thought_signature": "abc123"}}
    chat = ScriptedChat([audit_call("c1", extra=sig),
                         {"role": "assistant", "content": "requests is outdated"}])
    async with open_session() as session:
        answer = await run_agent_openai("audit", session, chat)
    assert answer == "requests is outdated"
    second_turn = chat.seen[1][0]
    assert second_turn[2]["tool_calls"][0]["extra_content"] == sig
    tool_msg = second_turn[3]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert "OUTDATED" in tool_msg["content"]
    assert chat.seen[0][0][0]["role"] == "system"


async def test_openai_agent_tools_are_function_schemas_without_unsupported_keys():
    chat = ScriptedChat([{"role": "assistant", "content": "done"}])
    async with open_session() as session:
        await run_agent_openai("x", session, chat)
    tools = chat.seen[0][1]
    assert {t["function"]["name"] for t in tools} == {"get_package_info", "audit_requirements"}
    blob = json.dumps(tools)
    assert '"title"' not in blob and "additionalProperties" not in blob


async def test_openai_agent_survives_malformed_tool_arguments():
    bad = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "audit_requirements", "arguments": "{not json"}}]}
    chat = ScriptedChat([bad, {"role": "assistant", "content": "recovered"}])
    async with open_session() as session:
        assert await run_agent_openai("x", session, chat) == "recovered"
    assert "Invalid tool call" in chat.seen[1][0][-1]["content"]


async def test_openai_agent_gives_up_after_max_rounds(fake_audit):
    chat = ScriptedChat([audit_call(f"c{i}") for i in range(3)])
    async with open_session() as session:
        with pytest.raises(RuntimeError):
            await run_agent_openai("x", session, chat, max_rounds=3)


def make_chat(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatChat("m1", "http://localhost:11434/v1/", "k", client=client, **kwargs)


OK_BODY = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}


async def test_openai_chat_sends_tools_and_auth():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["authorization"],
                    body=json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    msg = await make_chat(handler).complete([{"role": "user", "content": "q"}], [{"type": "function"}])
    assert msg["content"] == "hi"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["tools"] == [{"type": "function"}]


async def test_openai_chat_retries_rate_limits_then_succeeds(monkeypatch):
    sleeps, calls = [], []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(agent_module.asyncio, "sleep", fake_sleep)

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"retry-after": "2"}, text="slow down")
        return httpx.Response(200, json=OK_BODY)

    assert (await make_chat(handler).complete([], []))["content"] == "hi"
    assert len(calls) == 3 and sleeps == [2.0, 2.0]


async def test_openai_chat_fails_fast_on_daily_quota_and_shows_body(monkeypatch):
    async def fake_sleep(seconds):
        raise AssertionError("must not wait out a daily quota")

    monkeypatch.setattr(agent_module.asyncio, "sleep", fake_sleep)
    body = '{"error": {"details": [{"retryDelay": "3600s"}], "message": "quota exceeded"}}'

    with pytest.raises(httpx.HTTPStatusError, match="quota exceeded"):
        await make_chat(lambda request: httpx.Response(429, text=body)).complete([], [])


async def test_openai_chat_error_includes_response_body():
    with pytest.raises(httpx.HTTPStatusError, match="seed is not supported"):
        await make_chat(lambda r: httpx.Response(400, text="seed is not supported")).complete([], [])


def test_cli_provider_openai_uses_named_key_and_requires_model(monkeypatch, tmp_path, capsys):
    from depwatch import cli

    calls = []

    async def fake_run(task, model, provider, base_url, api_key):
        calls.append((model, provider, base_url, api_key))
        return "report"

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.19.0\n")
    argv = [str(req), "--provider", "openai", "--model", "gem", "--base-url", "http://x/v1",
            "--api-key-env", "GEMINI_API_KEY"]
    assert cli.main(argv) == 0
    assert calls == [("gem", "openai", "http://x/v1", "gem-key")]
    assert cli.main([str(req), "--provider", "openai", "--api-key-env", "GEMINI_API_KEY"]) == 2
    assert cli.main([str(req), "--provider", "openai"]) == 2
    assert "is not set" in capsys.readouterr().err


def test_agent_cli_reports_the_root_cause_not_an_exception_group(monkeypatch, capsys, tmp_path):
    from depwatch import cli

    async def failing_run(*args, **kwargs):
        group = Exception("unhandled errors in a TaskGroup")
        group.exceptions = [ValueError("429 from api")]  # shape of an (Base)ExceptionGroup
        raise group

    reqs = tmp_path / "requirements.txt"
    reqs.write_text("requests==2.19.0\n")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(cli, "_run", failing_run)
    argv = [str(reqs), "--provider", "openai", "--api-key-env", "GEMINI_API_KEY", "--model", "m"]
    assert cli.main(argv) == 1
    assert capsys.readouterr().err.strip() == "error: 429 from api"
