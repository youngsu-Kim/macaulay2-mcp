import asyncio
import stat
from pathlib import Path

import pytest

from macaulay2_mcp.config import (
    M2NotFoundError,
    UnsupportedM2Version,
    load_config,
)
from macaulay2_mcp.kernel import (
    M2ScriptRunner,
    M2Session,
    contains_m2_error,
    split_logical_inputs,
)

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


async def test_family_loop(session):
    """Beginner-facing pattern: compute invariants of a k-indexed ideal family
    in ONE evaluation using M2's for-loop syntax with ':=' locals."""
    result = await session.evaluate(
        "R = QQ[x,y,z]\n"
        "for k from 1 to 3 list (J := ideal(x^(k+2) - y, x^(k+3) - z); "
        "(k, #flatten entries generators gb J, dim (R/J)))"
    )
    assert "{(1, 4, 1), (2, 5, 1), (3, 6, 1)}" in result.output
    # session healthy afterwards
    assert "2" in (await session.evaluate("1 + 1")).output


async def test_timeout_kills_and_restarts(session):
    result = await session.evaluate("while true do()", timeout_s=3)
    assert result.timed_out
    assert "TIMED OUT" in result.output
    assert "NOT an error reported by Macaulay2" in result.output
    # session is fresh again
    fresh = await session.evaluate("1 + 1")
    assert "2" in fresh.output


async def test_interrupt_stops_runaway_and_preserves_state(session):
    await session.evaluate("keepAfterInterrupt = 99")
    task = asyncio.create_task(session.evaluate("while true do()", timeout_s=30))
    for _ in range(300):  # wait for the evaluation to enter busy state
        if session._busy:
            break
        await asyncio.sleep(0.05)
    assert session._busy, "evaluate never became busy"
    assert session.interrupt() is True
    result = await asyncio.wait_for(task, timeout=20)
    assert result.interrupted
    assert "error: interrupted" in result.output
    assert "stopped on request" in result.output
    # unlike a timeout, an interrupt keeps session state
    after = await session.evaluate("keepAfterInterrupt")
    assert "99" in after.output


async def test_interrupt_when_idle_is_noop(session):
    # never started
    assert session.interrupt() is False
    # started but nothing running
    await session.evaluate("1 + 1")
    assert session.interrupt() is False


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


# ---------------------------------------------------------------------------
# Logical-input splitter (pure function; no M2 needed)
# ---------------------------------------------------------------------------


def test_split_simple_lines():
    assert split_logical_inputs("a = 1\nb = 2\n") == ["a = 1", "b = 2"]


def test_split_keeps_multiline_input_together():
    code = "L = {1,\n2,\n3}\nsum L"
    assert split_logical_inputs(code) == ["L = {1,\n2,\n3}", "sum L"]


def test_split_attaches_comments_forward_and_drops_trailing():
    chunks = split_logical_inputs("-- lead\nx = 1\n\n-- tail\n")
    assert chunks == ["-- lead\nx = 1"]  # trailing comment dropped (would dangle)


def test_split_ignores_brackets_in_strings_and_comments():
    code = 's = "a{b"\nprint ") not a closer"\nc = 3'
    assert split_logical_inputs(code) == ['s = "a{b"', 'print ") not a closer"', "c = 3"]


def test_split_known_limitation_trailing_operator():
    # Documented tradeoff: M2 would continue this line; our splitter cuts it.
    assert split_logical_inputs("y = 2 +\n3\n") == ["y = 2 +", "3"]


def test_contains_m2_error_signature():
    assert contains_m2_error("stdio:3:8:(3):[1]: error: no method for adjacent objects:")
    assert contains_m2_error("/opt/x/Classic.m2:2:10:(3):[9]: error: boom")
    assert not contains_m2_error('print "error: oops"\nerror: oops')
    assert not contains_m2_error("o2 = 15\n\no2 : ZZ")


# ---------------------------------------------------------------------------
# Handshake robustness & stop_on_error (require live M2)
# ---------------------------------------------------------------------------


async def test_trailing_comment_does_not_swallow_marker(session):
    # Regression: a dangling last line absorbs the marker's iN:-anchored
    # echo; the handshake must still complete via the unique marker text.
    result = await session.evaluate("1+1\n-- trailing note\n", timeout_s=20)
    assert not result.timed_out
    assert "2" in result.output


async def test_continue_mode_runs_past_errors(session):
    r = await session.evaluate("sBefore = 7\nnoSuchFn(1)\nsAfter = sBefore + 1")
    assert r.errored and not r.stopped
    after = await session.evaluate("sAfter")
    assert "8" in after.output  # REPL semantics: later inputs ran


async def test_stop_on_error_halts_before_side_effects(session):
    r = await session.evaluate(
        "p1 = 1\nnoSuchFn(9)\np2 = p1 + 1\np3 = p1 + 2",
        stop_on_error=True,
    )
    assert r.errored and r.stopped and r.not_sent == 2
    p2 = await session.evaluate("p2")
    assert "Symbol" in p2.output  # never assigned: halt worked
    p1 = await session.evaluate("p1")
    assert "1" in p1.output  # pre-error statements took effect
