from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}"
USER_AGENT = "depwatch-mcp/0.1"


class PackageNotFound(Exception):
    pass


def _days_since(iso_timestamp: str | None, now: datetime | None = None) -> int | None:
    if not iso_timestamp:
        return None
    released = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    if released.tzinfo is None:
        released = released.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - released).days


async def _get_json(client: httpx.AsyncClient, url: str, name: str) -> dict[str, Any]:
    resp = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    if resp.status_code == 404:
        raise PackageNotFound(name)
    resp.raise_for_status()
    return resp.json()


async def pypi_info(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    data = await _get_json(client, PYPI_URL.format(name=name), name)
    info = data["info"]
    files = data.get("urls") or []
    released = max((f["upload_time_iso_8601"] for f in files), default=None)
    return {
        "ecosystem": "pypi",
        "name": info["name"],
        "latest_version": info["version"],
        "released": released,
        "days_since_release": _days_since(released),
        "license": info.get("license_expression") or info.get("license") or None,
        "summary": info.get("summary"),
        "requires_python": info.get("requires_python"),
        "yanked": bool(info.get("yanked")),
        "release_count": len(data.get("releases", {})),
    }


async def npm_info(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    data = await _get_json(client, NPM_URL.format(name=name), name)
    latest = data["dist-tags"]["latest"]
    version = data["versions"][latest]
    released = data.get("time", {}).get(latest)
    return {
        "ecosystem": "npm",
        "name": data["name"],
        "latest_version": latest,
        "released": released,
        "days_since_release": _days_since(released),
        "license": version.get("license"),
        "summary": data.get("description"),
        "deprecated": version.get("deprecated"),
        "release_count": len(data.get("versions", {})),
    }


async def package_info(client: httpx.AsyncClient, ecosystem: str, name: str) -> dict[str, Any]:
    if ecosystem == "pypi":
        return await pypi_info(client, name)
    if ecosystem == "npm":
        return await npm_info(client, name)
    raise ValueError(f"Unsupported ecosystem: {ecosystem!r} (use 'pypi' or 'npm')")
