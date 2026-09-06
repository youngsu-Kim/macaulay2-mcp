"""Management of a persistent Macaulay2 kernel process.

Protocol (verified against M2 1.26.06 over piped stdin/stdout):

* Start with ``M2 -q --no-debug --no-tty --silent``. The kernel blocks on its
  first read; it prints no banner.
* When a line of input arrives, M2 prints ``iN : <input>`` (echo, with
  continuation lines indented), then the result (``oN = <value>`` and, for
  most types, ``oN : <type>``).
* IMPORTANT: with stdin left open, M2 does NOT print the next bare prompt
  after finishing a result — the next ``iM :`` line only appears together
  with the next input (or at EOF).
* Errors (``... error: ...``) are printed on M2's stderr; the server merges
  stderr into stdout at the OS level (one ordered pipe), so error text
  appears in place within the returned output, in true stream order.
* Blank or comment-only lines do not terminate a logical input: the next
  line read is absorbed as a continuation. A marker must therefore be a
  complete statement.
* Completion of an evaluation is detected with a two-step random marker:
  ``m2MCP<12hex> = 1`` appended after the code. Step 1: the marker's echo
  ``iM : m2MCP<...> = 1`` arrives strictly after all output of the code.
  Step 2: the marker's deterministic result ``oM = 1`` is consumed and
  discarded.
* Multi-line input (e.g. an unbalanced ``{ ... }``) is read as one logical
  input. Code with a syntax error that leaves the input unbalanced swallows
  the marker line; the resulting "syntax error" on stderr is detected and
  the session is restarted to resynchronize.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import (
    DEFAULT_TIMEOUT_S,
    MAX_TIMEOUT_S,
    STARTUP_TIMEOUT_S,
    M2Config,
    M2NotFoundError,
    M2StartupError,
    UnsupportedM2Version,
    clamp_timeout,
    load_config,
)

logger = logging.getLogger("macaulay2_mcp.kernel")


class KernelCrashed(Exception):
    """The M2 process exited unexpectedly."""


def ends_unbalanced(code: str) -> bool:
    """Return True if ``code`` ends with unbalanced ( [ { or an unterminated
    string literal (ignoring -- comments).

    M2 in pipe mode would wait forever for continuation lines in that case
    (swallowing the marker we append), so we reject such input up front.
    """
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    in_str = False
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == "-" and i + 1 < n and code[i + 1] == "-":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if c in "([{":
            stack.append(c)
        elif c in pairs and (not stack or stack.pop() != pairs[c]):
            return False  # extra closer: M2 will report the error itself
        i += 1
    return bool(stack) or in_str


@dataclass
class EvalResult:
    output: str
    timed_out: bool = False
    crashed: bool = False
    stderr: str = ""


@dataclass
class ScriptResult:
    output: str
    exit_code: int | None
    timed_out: bool = False
    stderr: str = ""


def timeout_message(
    timeout_s: int, *, context: str = "the shared M2 session", restart_note: str
) -> str:
    return (
        f"TIMED OUT: the Macaulay2 computation did not finish within {timeout_s} seconds.\n"
        f"This limit is enforced by the macaulay2-mcp server (its author-set default, "
        f"currently {MAX_TIMEOUT_S}s maximum) as a safety guard against runaway or "
        f"infinite computations hanging {context} — it is NOT an error reported by "
        f"Macaulay2.\n"
        f"{restart_note}"
    )


def _session_timeout_message(timeout_s: int) -> str:
    return timeout_message(
        timeout_s,
        restart_note=(
            "The session was restarted, so objects defined earlier (rings, ideals, ...) "
            "no longer exist.\n"
            "If this computation is legitimately expected to take longer, retry with a "
            "larger timeout, e.g. m2_evaluate(<code>, timeout_s=600), and include all "
            "setup (ring/ideal definitions) in the same code block."
        ),
    )


def _script_timeout_message(timeout_s: int) -> str:
    return timeout_message(
        timeout_s,
        context="the isolated Macaulay2 process",
        restart_note=(
            "The process was killed; its partial output (if any) is shown above.\n"
            "If this script is legitimately expected to take longer, retry with a "
            "larger timeout, e.g. m2_run_script(<path>, timeout_s=600)."
        ),
    )


class M2Session:
    """A persistent Macaulay2 kernel, started lazily and restarted on demand."""

    def __init__(self, config: M2Config | None = None) -> None:
        self._config = config
        self._proc: asyncio.subprocess.Process | None = None
        self._prompt_index = 0
        self._lock = asyncio.Lock()
        self._config_error: str | None = None

    # ------------------------------------------------------------------ setup

    def _ensure_config(self) -> M2Config:
        if self._config is None:
            try:
                self._config = load_config()
            except (M2NotFoundError, UnsupportedM2Version, M2StartupError) as exc:
                self._config_error = str(exc)
                raise
        return self._config

    async def _start(self) -> None:
        config = self._ensure_config()
        logger.info("starting M2 kernel: %s", " ".join(config.kernel_command()))
        # stderr is merged into stdout at the OS level so that M2's error
        # messages keep their true stream position within the returned output.
        self._proc = await asyncio.create_subprocess_exec(
            *config.kernel_command(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._prompt_index = 0
        assert self._proc.stderr is None
        # Probe: the kernel blocks on its first read, so verify it is alive by
        # sending a marker statement (a complete, no-side-effect assignment)
        # and waiting for both its echo and its deterministic result.
        marker = self._new_marker()
        try:
            await self._marker_handshake(marker, STARTUP_TIMEOUT_S, write=(marker + " = 1\n").encode())
        except (asyncio.TimeoutError, KernelCrashed) as exc:
            await self._kill()
            raise M2StartupError(
                "Macaulay2 started but did not respond to the startup probe."
            ) from exc

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await proc.wait()
            except ProcessLookupError:
                pass

    async def ensure_started(self) -> None:
        if self._proc is None or self._proc.returncode is not None:
            await self._kill()
            await self._start()

    @property
    def config_error(self) -> str | None:
        return self._config_error

    def _new_marker(self) -> str:
        # A valid M2 variable name (letters/digits), unique per call.
        return "m2MCP" + uuid.uuid4().hex[:12]

    # ------------------------------------------------------------- I/O loop

    async def _read_line(self, deadline: float) -> str:
        assert self._proc is not None and self._proc.stdout is not None
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=remaining)
        if not line:
            code = self._proc.returncode
            raise KernelCrashed(f"Macaulay2 exited unexpectedly (return code {code}).")
        return line.decode("utf-8", errors="replace")

    async def _marker_handshake(
        self, marker: str, timeout_s: float, *, write: bytes
    ) -> str:
        """Write ``write`` (which must end with the marker statement) and
        complete the two-step marker handshake.

        Step 1: read until the marker's echo ``iN : <marker> = 1`` — this
        arrives strictly after all output of the preceding code.
        Step 2: consume the marker's deterministic result ``oN = 1``.

        Returns everything printed before the marker's echo (input echoes
        included; marker lines excluded). Raises asyncio.TimeoutError or
        KernelCrashed.
        """
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(write)
        await self._proc.stdin.drain()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        echo_re = re.compile(rf"^i(\d+) : {re.escape(marker)} = 1[ \t]*\r?$")
        result_re = re.compile(r"^o(\d+) = 1[ \t]*\r?$")
        lines: list[str] = []
        marker_index: int | None = None
        while True:
            text = await self._read_line(deadline)
            if marker_index is None:
                m = echo_re.match(text)
                if m:
                    marker_index = int(m.group(1))
                    self._prompt_index = max(self._prompt_index, marker_index)
                    continue
                lines.append(text)
            else:
                m = result_re.match(text)
                if m and int(m.group(1)) == marker_index:
                    return "".join(lines)
                # Other lines between the echo and the marker result belong to
                # no one (blank lines); drop them.

    async def _send_and_wait(self, code: str, marker: str, timeout_s: float) -> str:
        """Send ``code`` followed by the marker statement.

        Returns the block printed before the marker's echo. Raises
        asyncio.TimeoutError or KernelCrashed.
        """
        payload = (code + "\n" + marker + " = 1\n").encode("utf-8")
        return await self._marker_handshake(marker, timeout_s, write=payload)

    # ------------------------------------------------------------- evaluate

    async def evaluate(
        self, code: str, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> EvalResult:
        """Evaluate M2 code in the persistent session.

        On timeout the kernel is killed and restarted (state is lost); the
        returned output explains this.
        """
        timeout_s = clamp_timeout(timeout_s)
        async with self._lock:
            try:
                await self.ensure_started()
            except (M2NotFoundError, UnsupportedM2Version, M2StartupError) as exc:
                return EvalResult(output=f"ERROR: {exc}")
            code = code.strip("\n")
            if not code.strip():
                return EvalResult(output="(empty input; nothing was evaluated)")
            if ends_unbalanced(code):
                return EvalResult(
                    output=(
                        "ERROR: the code ends with unbalanced ( [ { (or an "
                        "unterminated string); Macaulay2 would wait indefinitely "
                        "for the closing part. Balance the expression and retry."
                    )
                )
            marker = self._new_marker()
            logger.debug("evaluating %d chars of M2 code (timeout %ds)", len(code), timeout_s)
            try:
                block = await self._send_and_wait(code, marker, timeout_s)
            except asyncio.TimeoutError:
                logger.warning("evaluation timed out after %ds; restarting kernel", timeout_s)
                await self._kill()
                return EvalResult(output=_session_timeout_message(timeout_s), timed_out=True)
            except KernelCrashed as exc:
                logger.warning("kernel crashed: %s; restarting", exc)
                await self._kill()
                return EvalResult(
                    output=(
                        f"ERROR: the Macaulay2 kernel exited unexpectedly ({exc}). "
                        f"The session was restarted.\n"
                        "Please retry your computation; if it fails again, the code "
                        "may be triggering a kernel bug (try a smaller input or "
                        "m2_run_script in an isolated process)."
                    ),
                    crashed=True,
                )
            # stderr is merged into the stream, so M2's error text is already in
            # `block`, in true stream order.
            if "syntax error" in block:
                # An unbalanced syntax error may have swallowed the marker and
                # desynchronized the input stream; restart to be safe.
                logger.warning("syntax error desync; restarting kernel")
                await self._kill()
                return EvalResult(
                    output=(
                        f"{block.strip()}\n\n"
                        "NOTE: a syntax error left the session input stream "
                        "unsynchronized, so the session was restarted. All "
                        "objects defined earlier no longer exist — retry with "
                        "corrected, self-contained code."
                    ),
                    crashed=True,
                )
            output = block.strip()
            if not output:
                output = "(the code ran successfully and produced no output)"
            return EvalResult(output=output)

    async def reset(self) -> str:
        """Restart the kernel, discarding all session state."""
        async with self._lock:
            try:
                await self.ensure_started()
            except (M2NotFoundError, UnsupportedM2Version, M2StartupError) as exc:
                return f"ERROR: {exc}"
            await self._kill()
            try:
                await self._start()
            except (M2StartupError, KernelCrashed, asyncio.TimeoutError) as exc:
                return f"ERROR: failed to restart Macaulay2: {exc}"
            config = self._config
            assert config is not None
            return (
                f"Session reset: Macaulay2 {config.version_str} restarted at "
                f"{config.binary}. All previous state (rings, ideals, variables, "
                f"loaded packages) has been cleared."
            )

    async def close(self) -> None:
        async with self._lock:
            await self._kill()

    # ----------------------------------------------------------------- misc

    def describe(self) -> str:
        if self._config is None:
            if self._config_error:
                return f"unavailable ({self._config_error.splitlines()[0]})"
            return "not started"
        return f"M2 {self._config.version_str} at {self._config.binary}"


class M2ScriptRunner:
    """Run .m2 files in a fresh, isolated M2 process (no shared session)."""

    def __init__(self, config: M2Config | None = None) -> None:
        self._config = config

    async def run(self, path: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> ScriptResult:
        timeout_s = clamp_timeout(timeout_s)
        try:
            config = self._config or load_config()
        except (M2NotFoundError, UnsupportedM2Version, M2StartupError) as exc:
            return ScriptResult(output=f"ERROR: {exc}", exit_code=None)

        file = Path(path)
        if not file.is_absolute():
            return ScriptResult(
                output=f"ERROR: path must be absolute, got {path!r}. Use the full path.",
                exit_code=None,
            )
        if not file.is_file():
            return ScriptResult(output=f"ERROR: file not found: {path}", exit_code=None)

        cmd = [config.binary, "-q", "--no-debug", "--no-tty", "--silent", "--stop", str(file)]
        logger.info("running script: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merged: errors keep stream order
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            stdout, _ = await proc.communicate()
            partial = stdout.decode("utf-8", errors="replace").strip()
            message = _script_timeout_message(timeout_s)
            if partial:
                message = f"{partial}\n\n{message}"
            return ScriptResult(output=message, exit_code=proc.returncode, timed_out=True)
        return ScriptResult(
            output=_strip_trailing_prompt(stdout.decode("utf-8", errors="replace")),
            exit_code=proc.returncode,
        )


def _strip_trailing_prompt(text: str) -> str:
    """M2 prints a bare ``iN :`` prompt when batch-mode stdin hits EOF.

    It is protocol noise for callers of m2_run_script; drop it.
    """
    return re.sub(r"\s*i\d+ :[ \t\r\n]*$", "", text).strip()
