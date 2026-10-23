from __future__ import annotations

import os
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from depwatch import audit

INDEX = (Path(__file__).parent / "static" / "index.html").read_text()
MAX_REQUIREMENTS_CHARS = 20_000


class InvalidInput(ValueError):
    """The request body is unusable; reported to the client as HTTP 400."""


async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(INDEX)


async def _requirements(request: Request) -> str:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise InvalidInput("Body must be a JSON object.")
    text = str(body.get("requirements", ""))
    if not text.strip():
        raise ValueError("Paste a requirements.txt first.")
    if len(text) > MAX_REQUIREMENTS_CHARS:
        raise ValueError("Input too large (max 20,000 characters).")
    return text


async def api_audit(request: Request) -> JSONResponse:
    try:
        text = await _requirements(request)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            return JSONResponse(await audit.audit_requirements(client, text))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except httpx.HTTPError as exc:
        return JSONResponse({"error": f"Registry request failed: {exc}"}, status_code=502)


def report_settings() -> tuple[str, str, str | None, str | None]:
    """AI-report backend from the environment: DEPWATCH_PROVIDER (anthropic|openai),
    DEPWATCH_MODEL, DEPWATCH_BASE_URL, DEPWATCH_API_KEY_ENV (name of the key variable)."""
    from depwatch.cli import DEFAULT_MODEL

    provider = os.environ.get("DEPWATCH_PROVIDER", "anthropic")
    key_env = os.environ.get("DEPWATCH_API_KEY_ENV") or (
        "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY")
    model = os.environ.get("DEPWATCH_MODEL") or (None if provider == "openai" else DEFAULT_MODEL)
    return provider, model or "", os.environ.get("DEPWATCH_BASE_URL"), os.environ.get(key_env)


async def api_report(request: Request) -> JSONResponse:
    provider, model, base_url, api_key = report_settings()
    if not api_key or not model:
        return JSONResponse(
            {"error": "AI reports are off. Set an API key (and DEPWATCH_MODEL for "
                      "DEPWATCH_PROVIDER=openai), then restart."}, status_code=503)
    try:
        text = await _requirements(request)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    from depwatch.cli import _run

    try:
        report = await _run(f"Audit this requirements.txt:\n\n{text}", model, provider,
                            base_url, api_key)
    except (httpx.HTTPError, RuntimeError) as exc:
        return JSONResponse({"error": f"AI report failed: {exc}"}, status_code=502)
    return JSONResponse({"report": report})


app = Starlette(routes=[
    Route("/", index),
    Route("/api/audit", api_audit, methods=["POST"]),
    Route("/api/report", api_report, methods=["POST"]),
])


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
