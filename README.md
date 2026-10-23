# depwatch-mcp

An [MCP](https://modelcontextprotocol.io) server that gives AI agents live dependency-health
data from PyPI and npm, plus a Claude agent that audits a `requirements.txt` and writes an
upgrade report.

```
requirements.txt ──► Claude ──► MCP tools ──► PyPI / npm registries (live)
                       ▲            │
                       └── flags ◄──┘   OUTDATED · UNPINNED · STALE · LATEST_YANKED · ...
```

## Demo (no API key needed)

```bash
pip install -e ".[dev]"
depwatch-web          # open http://127.0.0.1:8000
```

Paste a `requirements.txt` and click **Audit**: each package is checked live against PyPI and shown
in a table with colored flags. **Write AI report** additionally needs an API key (see "Run the agent" below)
(the agent calls the MCP tools and writes the report).

## MCP tools

| Tool | What it returns |
| --- | --- |
| `get_package_info(ecosystem, name)` | Latest version, release date and age, license, yanked (PyPI) or deprecation notice (npm) |
| `audit_requirements(requirements_txt)` | Per-package flags: `OUTDATED`, `UNPINNED`, `STALE` (no release in 2+ years), `LATEST_YANKED`, `NO_LICENSE_METADATA`, `NOT_FOUND_ON_PYPI` |

Example (real registry data): `requests==2.19.0` is flagged `OUTDATED`; `left-pad` on npm
reports its deprecation notice.

## Use the server from any MCP client

```json
{ "mcpServers": { "depwatch": { "command": "depwatch-mcp-server" } } }
```

## Run the agent

The agent runs on Claude by default, or on any OpenAI-compatible tool-calling API (OpenAI, Gemini,
Ollama, vLLM). Live runs make real, billable API calls.

```bash
pip install -e ".[dev]"

# Claude (default)
export ANTHROPIC_API_KEY=...
depwatch-agent requirements.txt

# Gemini, via Google's OpenAI-compatible endpoint (use a current model name)
GEMINI_API_KEY=... depwatch-agent requirements.txt \
    --provider openai --api-key-env GEMINI_API_KEY --model <gemini-model> \
    --base-url https://generativelanguage.googleapis.com/v1beta/openai
```

The web demo's **Write AI report** button reads the same settings from the environment:
`DEPWATCH_PROVIDER` (`anthropic` or `openai`), `DEPWATCH_MODEL`, `DEPWATCH_BASE_URL` and
`DEPWATCH_API_KEY_ENV` (the name of the variable holding the key).

## Tests

```bash
python -m pytest
ruff check src tests
```

Registry and audit logic are tested offline with a mocked HTTP transport; the MCP server is
tested over an in-memory transport; both agent backends use scripted fake models, and the
OpenAI-compatible client is tested against a mocked transport (request format, retries on
429/5xx, error bodies, provider metadata echoed back). A live agent run has not been recorded
here yet.

## Limitations

- `audit_requirements` covers Python requirements only; npm is lookup-only for now.
- It checks version freshness and metadata. It does not scan for known vulnerabilities (CVEs).
- Only `==` pins are compared against the latest version.
