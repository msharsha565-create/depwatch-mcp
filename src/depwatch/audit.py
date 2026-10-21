from __future__ import annotations

import asyncio
from typing import Any

import httpx
from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from depwatch.registry import PackageNotFound, pypi_info

STALE_AFTER_DAYS = 730


def parse_requirements(text: str) -> tuple[list[Requirement], list[str]]:
    """Returns parsed requirements and the lines that could not be parsed."""
    reqs, skipped = [], []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):  # -r, -e, --index-url ...
            skipped.append(raw.strip())
            continue
        try:
            reqs.append(Requirement(line))
        except InvalidRequirement:
            skipped.append(raw.strip())
    return reqs, skipped


def _pinned_version(req: Requirement) -> str | None:
    for spec in req.specifier:
        if spec.operator in ("==", "==="):
            return spec.version
    return None


def assess(req: Requirement, info: dict[str, Any]) -> dict[str, Any]:
    pinned = _pinned_version(req)
    flags: list[str] = []
    if pinned:
        try:
            if Version(pinned) < Version(info["latest_version"]):
                flags.append("OUTDATED")
        except InvalidVersion:
            flags.append("UNCOMPARABLE_VERSION")
    else:
        flags.append("UNPINNED")
    days = info["days_since_release"]
    if days is not None and days > STALE_AFTER_DAYS:
        flags.append("STALE")
    if info["yanked"]:
        flags.append("LATEST_YANKED")
    if not info["license"]:
        flags.append("NO_LICENSE_METADATA")
    return {
        "name": req.name,
        "specifier": str(req.specifier) or None,
        "pinned": pinned,
        "latest": info["latest_version"],
        "days_since_release": days,
        "license": info["license"],
        "flags": flags,
    }


async def audit_requirements(client: httpx.AsyncClient, text: str) -> dict[str, Any]:
    reqs, skipped = parse_requirements(text)

    async def one(req: Requirement) -> dict[str, Any]:
        try:
            return assess(req, await pypi_info(client, req.name))
        except PackageNotFound:
            return {"name": req.name, "flags": ["NOT_FOUND_ON_PYPI"]}

    packages = await asyncio.gather(*(one(r) for r in reqs))
    return {
        "packages": packages,
        "needs_attention": sum(1 for p in packages if p["flags"]),
        "skipped_lines": skipped,
    }
