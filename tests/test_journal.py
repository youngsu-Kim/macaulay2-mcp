"""Journal tests: unit behavior + a live round through the MCP server."""

import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_types import Implementation

from macaulay2_mcp.config import M2NotFoundError, UnsupportedM2Version, load_config
from macaulay2_mcp.journal import ENV_VAR, Journal


def _m2_available() -> bool:
    try:
        load_config()
    except (M2NotFoundError, UnsupportedM2Version):
        return False
    return True


# ---------------------------------------------------------------------- units


def test_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "off")
    j = Journal.from_env("0.1.0")
    assert not j.enabled
    j.record("evaluate", code="x")  # must be a silent no-op
    assert list(tmp_path.iterdir()) == []


def test_from_env_default_is_cwd_dotdir(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    j = Journal.from_env("0.1.0")
    assert j.enabled
    assert j.path.parent == tmp_path / ".m2-mcp"


def test_from_env_custom_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "logs"))
    j = Journal.from_env("0.1.0")
    j.record("evaluate", code="1")
    assert j.path.parent == tmp_path / "logs"


def test_header_lazy_and_carries_client_info(tmp_path):
    j = Journal(tmp_path, "0.1.0")
    j.set_client_info({"name": "claude-code", "version": "1.2.3"})
    j.record("evaluate", code="x=1", output="o2 = 1")
    lines = [json.loads(l) for l in j.path.read_text().splitlines()]
    assert lines[0]["event"] == "session"
    assert lines[0]["client"]["name"] == "claude-code"
    assert lines[0]["server_version"] == "0.1.0"
    assert lines[1]["event"] == "evaluate"
    assert lines[1]["seq"] == 1
    assert lines[1]["output"] == "o2 = 1"


def test_client_info_arriving_after_header_emits_record(tmp_path):
    j = Journal(tmp_path, "0.1.0")
    j.record("os_block", tool="m2_evaluate")  # writes header (client unknown yet)
    j.set_client_info({"name": "opencode", "version": "4.5"})
    j.record("evaluate", code="1")
    lines = [json.loads(l) for l in j.path.read_text().splitlines()]
    assert lines[0]["client"] is None
    client_recs = [l for l in lines if l["event"] == "client"]
    assert len(client_recs) == 1
    assert client_recs[0]["client"]["name"] == "opencode"


def test_large_fields_truncated(tmp_path):
    j = Journal(tmp_path, "0.1.0")
    j.record("evaluate", output="A" * 2_000_000)
    line = json.loads(j.path.read_text().splitlines()[1])
    assert "[truncated" in line["output"]
    assert len(line["output"]) < 2_000_000


def test_bad_dir_disables_without_raising(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir")
    j = Journal(blocker / "sub", "0.1.0")  # mkdir fails at construction
    assert not j.enabled
    j.record("evaluate", code="x")  # must not raise


def test_write_failure_disables_journal(tmp_path):
    j = Journal(tmp_path, "0.1.0")
    j.record("evaluate", code="1")  # header written OK
    assert j.enabled
    rmtree = tmp_path
    import shutil

    shutil.rmtree(rmtree)  # next write must fail
    j.record("evaluate", code="2")  # swallowed, self-disables
    assert j.path is None
    j.record("evaluate", code="3")  # already disabled: still no error


# --------------------------------------------------------------- live client


@pytest.mark.skipif(not _m2_available(), reason="needs M2 1.26")
async def test_live_journal_captures_events_and_client(tmp_path):
    logdir = tmp_path / "jlogs"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "macaulay2_mcp"],
        env={**os.environ, ENV_VAR: str(logdir)},
    )
    async with stdio_client(params) as (r, w), ClientSession(
        r, w, client_info=Implementation(name="journal-test-client", version="9.9")
    ) as session:
        await session.initialize()
        await session.call_tool("m2_evaluate", {"code": "jj = 40 + 1"})
        await session.call_tool("m2_evaluate", {"code": 'runProgram "ls"'})

    files = list(logdir.glob("session-*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(l) for l in files[0].read_text().splitlines()]
    header = lines[0]
    assert header["event"] == "session"
    # the connected MCP host (i.e., which LLM client drove this session):
    assert header["client"]["name"] == "journal-test-client"
    assert header["client"]["version"] == "9.9"
    events = [l["event"] for l in lines[1:]]
    assert events == ["evaluate", "os_block"]
    ok = lines[1]
    assert ok["code"] == "jj = 40 + 1"
    assert "41" in ok["output"]
    assert "journal-test-client" not in ok  # client only in header
    blocked = lines[2]
    assert blocked["tool"] == "m2_evaluate"
    assert blocked["symbols"] == ["runProgram"]
    assert 'runProgram "ls"' in blocked["code"]
