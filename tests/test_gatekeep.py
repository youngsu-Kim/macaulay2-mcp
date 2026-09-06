"""Gatekeeper tests: unit scanning + live integration through the server."""

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

# stdio spawns get only a curated env — pass JOURNAL=off explicitly (finding F12)
SERVER_ENV = {**get_default_environment(), "MACAULAY2_MCP_JOURNAL": "off"}

from macaulay2_mcp.config import M2NotFoundError, UnsupportedM2Version, load_config
from macaulay2_mcp.gatekeep import (
    OS_SYMBOLS,
    allowed_symbols,
    check_package_name,
    find_blocked_calls,
    rejection_message,
)


def _m2_available() -> bool:
    try:
        load_config()
    except (M2NotFoundError, UnsupportedM2Version):
        return False
    return True


# --------------------------------------------------------------------- units


def test_detects_direct_calls():
    assert find_blocked_calls('runProgram "ls -la"') == ["runProgram"]
    assert "system" in find_blocked_calls('system("rm -rf /")')


def test_strings_and_comments_are_masked():
    assert find_blocked_calls('print "do not call runProgram"') == []
    assert find_blocked_calls("-- lines(\"/etc/passwd\") is evil\nx = 1") == []
    # mention in real code AFTER a string is still caught:
    assert find_blocked_calls('s = "runProgram"\nrunProgram s') == ["runProgram"]


def test_word_boundaries():
    assert find_blocked_calls("myRunProgram = 5") == []  # not the symbol
    assert find_blocked_calls("Pkg`runProgram") == ["runProgram"]  # package-qualified


def test_multiple_symbols_sorted_unique():
    hits = find_blocked_calls("lines f\nquit\nrunProgram cmd\nlines g")
    assert hits == ["lines", "quit", "runProgram"]


def test_allowlist_env(monkeypatch):
    monkeypatch.setenv("MACAULAY2_MCP_OS_ALLOW", "lines, openOut")
    assert allowed_symbols() == frozenset({"lines", "openOut"})
    assert find_blocked_calls('f = openOut "x"; lines "y"') == []
    assert find_blocked_calls("quit") == ["quit"]


def test_package_name_guard():
    assert check_package_name("BoijSoederberg") is None
    assert "BLOCKED" in check_package_name("/tmp/evil.m2")
    assert "BLOCKED" in check_package_name("../outside/pkg")
    assert "BLOCKED" in check_package_name("sneaky/Thing")


def test_rejection_message_contract():
    msg = rejection_message("runProgram")
    assert "BLOCKED" in msg
    assert "Nothing was executed" in msg
    assert "MACAULAY2_MCP_OS_ALLOW" in msg  # how to enable, reversibly
    assert "not a sandbox" in msg  # honesty clause


def test_list_covers_verified_surface():
    # symbols verified present-or-absent in M2 1.26.06 during design:
    for s in ("runProgram", "lines", "openOut", "openIn", "installPackage", "quit"):
        assert s in OS_SYMBOLS


# ------------------------------------------------------ live integration


async def _with_server(fn):
    params = StdioServerParameters(command=sys.executable, args=["-m", "macaulay2_mcp"], env=SERVER_ENV)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await fn(session)


@pytest.mark.skipif(not _m2_available(), reason="needs M2 1.26")
async def test_evaluate_blocked_and_session_untouched():
    async def run(session: ClientSession):
        blocked = await session.call_tool("m2_evaluate", {"code": 'runProgram "echo pwned"'})
        fine = await session.call_tool("m2_evaluate", {"code": "gateSafe = 6*7"})
        return blocked.content[0].text, fine.content[0].text

    blocked_text, fine_text = await _with_server(run)
    assert "BLOCKED" in blocked_text and "runProgram" in blocked_text
    assert "42" in fine_text  # gate never touched the session


@pytest.mark.skipif(not _m2_available(), reason="needs M2 1.26")
async def test_run_script_blocked(tmp_path):
    script = tmp_path / "evil.m2"
    script.write_text('print lines "/etc/hosts"\n')

    async def run(session: ClientSession):
        r = await session.call_tool("m2_run_script", {"path": str(script)})
        return r.content[0].text

    text = await _with_server(run)
    assert "BLOCKED" in text and "lines" in text


@pytest.mark.skipif(not _m2_available(), reason="needs M2 1.26")
async def test_import_file_blocked(tmp_path):
    f = tmp_path / "defs.m2"
    f.write_text('readme = lines "/etc/hosts"\n')

    async def run(session: ClientSession):
        r = await session.call_tool("m2_import_file", {"path": str(f)})
        return r.content[0].text

    text = await _with_server(run)
    assert "BLOCKED" in text
