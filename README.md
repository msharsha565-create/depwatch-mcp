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
in a table with colored flags. **Write AI report** additionally needs `ANTHROPIC_API_KEY`
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

## Run the agent (live)

Needs an Anthropic API key; this makes real API calls.

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...
depwatch-agent requirements.txt
```

## Tests

```bash
python -m pytest
ruff check src tests
```

Registry and audit logic are tested offline with a mocked HTTP transport; the MCP server is
tested over an in-memory transport; the agent loop uses a scripted fake Anthropic client. The
live agent run is exercised manually.

## Limitations

- `audit_requirements` covers Python requirements only; npm is lookup-only for now.
- It checks version freshness and metadata. It does not scan for known vulnerabilities (CVEs).
- Only `==` pins are compared against the latest version.
