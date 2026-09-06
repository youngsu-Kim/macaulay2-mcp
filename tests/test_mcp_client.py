"""Client-level tests: speak real MCP to the server over stdio."""

import asyncio
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

# stdio spawns get only a curated env — pass JOURNAL=off explicitly (finding F12)
SERVER_ENV = {**get_default_environment(), "MACAULAY2_MCP_JOURNAL": "off"}

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
    params = StdioServerParameters(command=sys.executable, args=["-m", "macaulay2_mcp"], env=SERVER_ENV)
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
    params = StdioServerParameters(command=sys.executable, args=["-m", "macaulay2_mcp"], env=SERVER_ENV)
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


async def test_concurrent_evaluates_are_serialized_safely():
    """Many simultaneous m2_evaluate calls must each receive exactly their
    own result (the shared session lock serializes them against one kernel)."""
    codes = [
        ("1 + 1", "2"),
        ("222 + 333", "555"),
        ("6 * 7", "42"),
    ]
    params = StdioServerParameters(command=sys.executable, args=["-m", "macaulay2_mcp"], env=SERVER_ENV)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        results = await asyncio.gather(
            *(session.call_tool("m2_evaluate", {"code": code}) for code, _ in codes)
        )
        for r, (code, value) in zip(results, codes):
            assert not r.is_error
            text = r.content[0].text
            assert code in text  # its own echo
            assert f"= {value}" in text  # its own result
        # session still healthy after the concurrent burst
        final = await session.call_tool("m2_evaluate", {"code": "9 - 4"})
        assert "5" in final.content[0].text


async def test_concurrent_run_scripts(tmp_path):
    """m2_run_script takes no session lock: several jobs genuinely run as
    parallel isolated M2 processes. Assert correctness (never timing)."""
    scripts, values = [], []
    for k in (1, 2, 3):
        f = tmp_path / f"job{k}.m2"
        f.write_text(
            "R = QQ[x,y,z]\n"
            f"J := ideal(x^({k + 2}) - y, x^({k + 3}) - z)\n"
            'print ("gbGens=" | toString (#flatten entries generators gb J))\n'
        )
        scripts.append(str(f))
        values.append(f"gbGens={k + 3}")
    params = StdioServerParameters(command=sys.executable, args=["-m", "macaulay2_mcp"], env=SERVER_ENV)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        results = await asyncio.gather(
            *(session.call_tool("m2_run_script", {"path": p}) for p in scripts)
        )
        for r, expected in zip(results, values):
            assert not r.is_error
            assert expected in r.content[0].text


async def test_error_note_appears_and_absent_on_success():
    async def run(session: ClientSession):
        bad = await session.call_tool("m2_evaluate", {"code": "noSuchFn(1)\nxNote = 5"})
        good = await session.call_tool("m2_evaluate", {"code": "2+2"})
        return bad.content[0].text, good.content[0].text

    bad_text, good_text = await _with_server(run)
    assert "ask the user" in bad_text and "CONTINUE" in bad_text
    assert "5" in bad_text  # the later line ran (REPL semantics visible)
    assert "ask the user" not in good_text and "4" in good_text


async def test_stop_on_error_via_mcp():
    async def run(session: ClientSession):
        halted = await session.call_tool(
            "m2_evaluate",
            {"code": "q1 = 1\nnoSuchFn(9)\nq2 = 2", "stop_on_error": True},
        )
        probe = await session.call_tool("m2_evaluate", {"code": "q2"})
        return halted.content[0].text, probe.content[0].text

    halted_text, probe_text = await _with_server(run)
    assert "were NOT executed" in halted_text
    assert "Symbol" in probe_text  # q2 never ran


async def test_evaluate_schema_has_stop_on_error():
    async def get(session: ClientSession):
        tools = await session.list_tools()
        schema = {t.name: t.input_schema for t in tools.tools}["m2_evaluate"]
        return schema["properties"].keys()

    props = await _with_server(get)
    assert {"code", "timeout_s", "stop_on_error"} <= set(props)
