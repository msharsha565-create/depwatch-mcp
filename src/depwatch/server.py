from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from depwatch import audit, registry

mcp = FastMCP("depwatch")


@mcp.tool()
async def get_package_info(ecosystem: str, name: str) -> dict[str, Any]:
    """Latest version, release date, license and status of a package.
    ecosystem is 'pypi' or 'npm'."""
    async with httpx.AsyncClient(timeout=20) as client:
        return await registry.package_info(client, ecosystem, name)


@mcp.tool()
async def audit_requirements(requirements_txt: str) -> dict[str, Any]:
    """Audit the text of a Python requirements.txt against PyPI. Flags per package:
    OUTDATED, UNPINNED, STALE (no release in 2+ years), LATEST_YANKED,
    NO_LICENSE_METADATA, NOT_FOUND_ON_PYPI."""
    async with httpx.AsyncClient(timeout=20) as client:
        return await audit.audit_requirements(client, requirements_txt)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
