"""Client-level tests: speak real MCP to the server over stdio."""

import asyncio
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from macaulay2_mcp.config import M2NotFoundError, UnsupportedM2Version, load_config

EXPECTED_TOOLS = {
    "m2_evaluate",
    "m2_interrupt",
    "m2_session_reset",
    "m2_help",
    "m2_run_script",
    "m2_list_packages",
    "m2_load_package",
    "m2_import_file",
}


def _m2_available() -> bool:
    try:
        load_config()
    except (M2NotFoundError, UnsupportedM2Version):
        return False
    return True


pytestmark = pytest.mark.skipif(not _m2_available(), reason="needs M2 1.26")


async def _with_server(fn):
    params = StdioServerParameters(command=sys.executable, args=["-m", "macaulay2_mcp"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await fn(session)


async def test_lists_seven_tools():
    async def get(session: ClientSession):
        tools = await session.list_tools()
        return {t.name for t in tools.tools}

    assert await _with_server(get) == EXPECTED_TOOLS


async def test_evaluate_via_mcp():
    async def get(session: ClientSession):
        result = await session.call_tool("m2_evaluate", {"code": "R = QQ[x,y]\nx^2"})
        assert not result.is_error
        return result.content[0].text

    text = await _with_server(get)
    assert "PolynomialRing" in text


async def test_help_via_mcp():
    async def get(session: ClientSession):
        result = await session.call_tool("m2_help", {"topic": "groebnerBasis"})
        assert not result.is_error
        return result.content[0].text

    text = await _with_server(get)
    assert "roebner" in text


async def test_import_file_via_mcp(tmp_path):
    file = tmp_path / "defs.m2"
    file.write_text("importedValue = 77\n")

    async def get(session: ClientSession):
        r1 = await session.call_tool(
            "m2_import_file", {"path": str(file)}
        )
        r2 = await session.call_tool("m2_evaluate", {"code": "importedValue"})
        assert not r1.is_error and not r2.is_error
        return r2.content[0].text

    assert "77" in await _with_server(get)


async def test_load_preloaded_package_reports_already_loaded():
    """Preloaded package => 'already loaded' note, no forced (fragile) reload."""

    async def get(session: ClientSession):
        result = await session.call_tool("m2_load_package", {"name": "Complexes"})
        assert not result.is_error
        return result.content[0].text

    text = await _with_server(get)
    assert "already loaded" in text
    assert "error" not in text.lower()


async def test_interrupt_idle_via_mcp():
    async def get(session: ClientSession):
        result = await session.call_tool("m2_interrupt", {})
        assert not result.is_error
        return result.content[0].text

    assert "Nothing is running" in await _with_server(get)


async def test_interrupt_running_computation_via_mcp():
    """Concurrent MCP calls: cancel a runaway m2_evaluate with m2_interrupt.

    Exercises the exact production pattern: the client waits on m2_evaluate
    (the session lock is held) while m2_interrupt runs on a second request
    and must NOT deadlock — proving the lock-free interrupt path.
    """
    params = StdioServerParameters(command=sys.executable, args=["-m", "macaulay2_mcp"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        setup = await session.call_tool("m2_evaluate", {"code": "keepMe = 99"})
        assert not setup.is_error

        async def runaway():
            res = await session.call_tool(
                "m2_evaluate", {"code": "while true do()", "timeout_s": 60}
            )
            return res.content[0].text

        task = asyncio.create_task(runaway())
        await asyncio.sleep(3.0)  # let the kernel enter the loop
        inter = await session.call_tool("m2_interrupt", {})
        assert not inter.is_error
        assert "Interrupt sent" in inter.content[0].text
        text = await asyncio.wait_for(task, timeout=30)
        assert "error: interrupted" in text
        assert "stopped on request" in text

        kept = await session.call_tool("m2_evaluate", {"code": "keepMe"})
        assert "99" in kept.content[0].text
