"""Append-only JSONL journal of every MCP <-> M2 interaction.

Why: this project was debugged by staring at pipe transcripts, and researchers
(and the assistants acting for them) deserve a durable, machine-readable audit
trail of exactly what code ran and what M2 answered — including attempts the
gatekeeper refused. It is also the substrate for future checkpoint/replay.

Layout (default on): ``./.m2-mcp/session-<UTC>-<pid>.jsonl`` in the working
directory of the MCP host, one JSON object per line:

* first line: ``{"event": "session", ...}`` header (server version, M2 info
  when known, cwd, pid, clientInfo as soon as the initialize handshake is
  observed);
* then one record per event: evaluate / run_script / import_file /
  load_package / help / list_packages / reset / interrupt / os_block /
  client (a late-arriving clientInfo).

Configuration: ``MACAULAY2_MCP_JOURNAL=<dir>`` relocates the journal;
``MACAULAY2_MCP_JOURNAL=off`` disables it entirely.

Guarantees: journaling NEVER raises into the tool path and NEVER writes to
stdout. On the first I/O failure the journal disables itself and warns once
on stderr. Large string fields are truncated at ``MAX_FIELD_BYTES`` with an
explicit ``...[truncated N bytes]`` marker so records stay parseable.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("macaulay2_mcp.journal")

ENV_VAR = "MACAULAY2_MCP_JOURNAL"
DEFAULT_DIRNAME = ".m2-mcp"
MAX_FIELD_BYTES = 1_048_576  # 1 MiB per string field


def _truncate(value: str, limit: int = MAX_FIELD_BYTES) -> str:
    data = value.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return value
    clipped = data[:limit].decode("utf-8", errors="ignore")
    return clipped + f"\n...[truncated {len(data) - limit} bytes]"


class Journal:
    def __init__(self, base_dir: Path | None, server_version: str) -> None:
        """base_dir=None means disabled."""
        self._server_version = server_version
        self._path: Path | None = None
        self._seq = 0
        self._header_written = False
        self._client: dict | None = None
        self._client_recorded = False
        self._m2_info: dict | None = None
        self._disabled_reason: str | None = None
        if base_dir is not None:
            try:
                base_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                self._path = base_dir / f"session-{stamp}-{os.getpid()}.jsonl"
            except OSError as exc:
                self._disabled_reason = f"cannot create {base_dir}: {exc}"
                self._path = None

    # --------------------------------------------------------------- factory

    @classmethod
    def from_env(cls, server_version: str) -> Journal:
        raw = os.environ.get(ENV_VAR, "").strip()
        if raw.lower() in ("off", "false", "0", "none"):
            return cls(None, server_version)
        base = Path(raw).expanduser() if raw else Path.cwd() / DEFAULT_DIRNAME
        return cls(base, server_version)

    @property
    def enabled(self) -> bool:
        return self._path is not None

    @property
    def path(self) -> Path | None:
        return self._path

    # ------------------------------------------------------------------ API

    def set_client_info(self, info: dict | None) -> None:
        """Called from tool handlers once the initialize handshake is known."""
        if info is None or self._client is not None:
            return
        self._client = info
        if self._header_written and not self._client_recorded:
            # header already on disk; emit a dedicated record instead
            self._client_recorded = True
            self.record("client", client=info)

    def set_m2_info(self, info: dict | None) -> None:
        if info and self._m2_info is None and not self._header_written:
            self._m2_info = info

    def record(self, event: str, **fields) -> None:
        if self._path is None:
            return
        try:
            if not self._header_written:
                self._write(self._header())
                self._header_written = True
                self._seq = 1  # header holds seq 0; records count from 1
            record = {"t": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                      "seq": self._seq, "event": event}
            self._seq += 1
            for key, value in fields.items():
                if isinstance(value, str):
                    value = _truncate(value)
                record[key] = value
            self._write(record)
        except Exception as exc:  # noqa: BLE001 - journaling must never break a tool call
            self._path = None
            print(
                f"macaulay2-mcp: journal disabled after error: {exc}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------- internals

    def _header(self) -> dict:
        return {
            "t": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "seq": self._seq,
            "event": "session",
            "journal_version": 1,
            "server_version": self._server_version,
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "m2": self._m2_info,
            "client": self._client,
        }

    def _write(self, obj: dict) -> None:
        assert self._path is not None
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
