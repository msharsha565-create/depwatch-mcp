import httpx
import pytest

from depwatch.audit import audit_requirements, parse_requirements
from depwatch.registry import PackageNotFound, package_info

OLD = "2015-01-01T00:00:00.000000Z"


def pypi_doc(name, version, uploaded, yanked=False, license_="MIT"):
    return {
        "info": {"name": name, "version": version, "license": license_, "summary": "s",
                 "requires_python": ">=3.8", "yanked": yanked},
        "urls": [{"upload_time_iso_8601": uploaded}],
        "releases": {version: []},
    }


def make_client(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        doc = routes.get(request.url.path)
        return httpx.Response(200, json=doc) if doc else httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_pypi_info_parses_fields():
    async with make_client({"/pypi/foo/json": pypi_doc("foo", "1.2.0", OLD)}) as c:
        info = await package_info(c, "pypi", "foo")
    assert info["latest_version"] == "1.2.0"
    assert info["days_since_release"] > 3000
    assert info["license"] == "MIT"


async def test_npm_info_reports_deprecation():
    doc = {"name": "left-pad", "description": "pad", "dist-tags": {"latest": "1.3.0"},
           "time": {"1.3.0": OLD},
           "versions": {"1.3.0": {"license": "WTFPL", "deprecated": "use padStart"}}}
    async with make_client({"/left-pad": doc}) as c:
        info = await package_info(c, "npm", "left-pad")
    assert info["deprecated"] == "use padStart"


async def test_unknown_package_and_ecosystem():
    async with make_client({}) as c:
        with pytest.raises(PackageNotFound):
            await package_info(c, "pypi", "nope")
        with pytest.raises(ValueError):
            await package_info(c, "cargo", "x")


def test_parse_requirements_skips_options_and_comments():
    reqs, skipped = parse_requirements("# c\nfoo==1.0  # x\n\n-r base.txt\n???\nbar>=2\n")
    assert [r.name for r in reqs] == ["foo", "bar"]
    assert skipped == ["-r base.txt", "???"]


async def test_audit_flags():
    routes = {
        "/pypi/old/json": pypi_doc("old", "2.0", OLD),
        "/pypi/yanked/json": pypi_doc("yanked", "1.0", "2999-01-01T00:00:00Z", yanked=True),
        "/pypi/fine/json": pypi_doc("fine", "1.0", "2999-01-01T00:00:00Z"),
        "/pypi/nolic/json": pypi_doc("nolic", "1.0", "2999-01-01T00:00:00Z", license_=None),
    }
    text = "old==1.0\nyanked==1.0\nfine==1.0\nnolic>=1\nghost==1\n"
    async with make_client(routes) as c:
        result = await audit_requirements(c, text)
    flags = {p["name"]: p["flags"] for p in result["packages"]}
    assert flags["old"] == ["OUTDATED", "STALE"]
    assert flags["yanked"] == ["LATEST_YANKED"]
    assert flags["fine"] == []
    assert flags["nolic"] == ["UNPINNED", "NO_LICENSE_METADATA"]
    assert flags["ghost"] == ["NOT_FOUND_ON_PYPI"]
    assert result["needs_attention"] == 4
