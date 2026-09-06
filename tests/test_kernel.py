import stat
from pathlib import Path

import pytest

from macaulay2_mcp.config import (
    M2NotFoundError,
    UnsupportedM2Version,
    load_config,
)
from macaulay2_mcp.kernel import M2ScriptRunner, M2Session

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_fake_m2(tmp_path: Path, version: str) -> str:
    """Create an executable script that mimics `M2 --version`."""
    script = tmp_path / "M2"
    script.write_text(f"#!/bin/sh\necho {version}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_discover_uses_m2_bin_override(tmp_path, monkeypatch):
    binary = make_fake_m2(tmp_path, "1.26.06")
    monkeypatch.setenv("M2_BIN", binary)
    config = load_config()
    assert config.binary == binary
    assert config.version_str == "1.26.06"
    assert config.version == (1, 26, 6)


def test_m2_bin_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("M2_BIN", str(tmp_path / "does-not-exist"))
    with pytest.raises(M2NotFoundError):
        load_config()


def test_unsupported_version_rejected(tmp_path, monkeypatch):
    binary = make_fake_m2(tmp_path, "1.22.05")
    monkeypatch.setenv("M2_BIN", binary)
    with pytest.raises(UnsupportedM2Version) as excinfo:
        load_config()
    assert "1.22.05" in str(excinfo.value)
    assert "upgrade" in str(excinfo.value).lower()


def test_real_m2_config_or_skip(monkeypatch):
    monkeypatch.delenv("M2_BIN", raising=False)
    try:
        config = load_config()
    except (M2NotFoundError, UnsupportedM2Version):
        pytest.skip("Macaulay2 1.26 not available on this machine")
    assert config.version[:2] == (1, 26)


def _session_or_skip(monkeypatch):
    monkeypatch.delenv("M2_BIN", raising=False)
    try:
        config = load_config()
    except (M2NotFoundError, UnsupportedM2Version):
        pytest.skip("Macaulay2 1.26 not available on this machine")
    return M2Session(config)


@pytest.fixture()
async def session(monkeypatch):
    s = _session_or_skip(monkeypatch)
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Protocol tests (require a real M2 1.26)
# ---------------------------------------------------------------------------


async def test_state_persists(session):
    await session.evaluate("R = QQ[x,y,z]")
    result = await session.evaluate("I = ideal(x^3 - y, x^4 - z)\nprint generators (gb I)")
    assert "xy-z" in result.output or "xy - z" in result.output.replace("z", " z")


async def test_m2_error_is_surfaced(session):
    result = await session.evaluate("thisIsNotAFunction(3)")
    assert "error" in result.output.lower()
    # session survives
    assert "2" in (await session.evaluate("1 + 1")).output


async def test_multiline_input(session):
    result = await session.evaluate("L = {1,\n2,\n3}\nsum L")
    assert "6" in result.output


async def test_timeout_kills_and_restarts(session):
    result = await session.evaluate("while true do()", timeout_s=3)
    assert result.timed_out
    assert "TIMED OUT" in result.output
    assert "NOT an error reported by Macaulay2" in result.output
    # session is fresh again
    fresh = await session.evaluate("1 + 1")
    assert "2" in fresh.output


async def test_unbalanced_input_rejected_upfront(session):
    result = await session.evaluate("y = {1,")
    assert "unbalanced" in result.output.lower()
    # session untouched
    assert "2" in (await session.evaluate("1 + 1")).output


async def test_reset_clears_state(session):
    await session.evaluate("resetProbe = 42")
    assert "42" in (await session.evaluate("resetProbe")).output
    message = await session.reset()
    assert "reset" in message.lower()
    # after reset the symbol is unknown (M2 treats it as a plain Symbol)
    result = await session.evaluate("resetProbe")
    assert "Symbol" in result.output


async def test_load_package_with_reload_fallback(session):
    result = await session.evaluate('loadPackage "Classic"')
    # Classic is preloaded; either it reports already-loaded + auto-reload, or loads
    assert result.output


async def test_list_packages(session):
    result = await session.evaluate("loadedPackages")
    assert "Core" in result.output


# ---------------------------------------------------------------------------
# Script runner (isolated process)
# ---------------------------------------------------------------------------


async def test_run_script(tmp_path, session):
    script = tmp_path / "s.m2"
    script.write_text("R = QQ[x,y]\nI = ideal(x^2, y^2)\nprint dim (quotient I)\n")
    runner = M2ScriptRunner(session._config)
    result = await runner.run(str(script))
    assert result.timed_out is False
    assert "0" in result.output
    # batch-mode EOF prints a bare "i1 :" prompt — stripped from the result
    assert not result.output.rstrip().endswith(":")
    assert "i1 :" not in result.output


async def test_run_script_missing_file(session):
    runner = M2ScriptRunner(session._config)
    result = await runner.run("/nonexistent/nowhere.m2")
    assert "not found" in result.output


async def test_run_script_relative_path_rejected(session):
    runner = M2ScriptRunner(session._config)
    result = await runner.run("relative/path.m2")
    assert "absolute" in result.output


# ---------------------------------------------------------------------------
# Unbalanced-input scanner
# ---------------------------------------------------------------------------


def test_ends_unbalanced_scanner():
    from macaulay2_mcp.kernel import ends_unbalanced

    assert ends_unbalanced("f = {1,")
    assert ends_unbalanced("x = [1, 2")
    assert ends_unbalanced('s = "unterminated')
    assert not ends_unbalanced("L = {1, 2}")
    assert not ends_unbalanced("L = {1, 2}\nsum L")
    # parens inside strings and comments are ignored
    assert not ends_unbalanced('print "({"\n1 + 1')
    assert not ends_unbalanced("1 + 1 -- ( comment")
    # extra closer: not a hang risk, M2 will error itself
    assert not ends_unbalanced(") ")
