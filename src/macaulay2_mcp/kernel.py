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
* Completion of an evaluation is detected with a random void marker:
  ``scan({}, i -> m2MCP<12hex>)`` appended after the code. A line ending
  with ``m2MCP<...>)`` arrives strictly after all output of the code —
  usually its own echo ``iM : scan({}, i -> m2MCP<...>)``, but indented if
  the code ended with a dangling line (e.g. a trailing comment) that
  absorbed the marker. The statement is COMPLETE (cannot dangle), produces
  NO ``oN =`` output line, and — unlike an assignment — does not pollute
  M2's ``oo``/``ooo`` output history, so tutorial-style workflows keep
  working. A void scan's *input* still consumes an ``iN`` label; that is
  harmless because matching is on the unique marker text.
* Multi-line input (e.g. an unbalanced ``{ ... }``) is read as one logical
  input. Code with a syntax error that leaves the input unbalanced swallows
  the marker line; the resulting "syntax error" on stderr is detected and
  the session is restarted to resynchronize.
* SIGINT (see :meth:`M2Session.interrupt`) aborts the current input at M2's
  safe checkpoints: ``error: interrupted`` is printed, prompt indices stay
  in sync, and the buffered marker still executes — so an in-flight
  ``evaluate()`` completes its handshake and returns normally. SIGINT while
  the kernel merely waits for input only emits a bare prompt line (filtered
  from evaluation blocks). Both behaviours verified on M2 1.26.06.
"""

from __future__ import annotations

import asyncio
import logging
import re
import signal
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
from .scanner import mask

logger = logging.getLogger("macaulay2_mcp.kernel")


class KernelCrashed(Exception):
    """The M2 process exited unexpectedly."""


# A line that is exactly a bare prompt (``iN :``). M2 emits these when it
# receives SIGINT while waiting for input; they carry no information and
# would otherwise pollute the next evaluation's block.
_BARE_PROMPT_RE = re.compile(r"^i\d+ :[ \t]*\r?$")

# A line whose masked text ENDS in something that cannot complete a logical
# input: a dangling binary/lambda operator or a continuation keyword. M2 keeps
# reading the next line in these cases even when brackets are balanced
# (e.g. the official Collatz example ``Collatz = n ->`` + body on the next
# line), so the splitter must not break there.
_DANGLING_RE = re.compile(
    r"(?:->|=>|\+\+|\*\*|//|\+|\*|-|/|\^|=|%|\||&|<|>|\?|@"
    r"|\b(?:if|then|else|do|where|while|for|list|sum|product|apply|scan|of"
    r"|suchThat|case|method|try)\b)[ \t]*$"
)


def ends_unbalanced(code: str) -> bool:
    """Return True if ``code`` ends with unbalanced ( [ { or an unterminated
    string literal (ignoring -- comments).

    M2 in pipe mode would wait forever for continuation lines in that case
    (swallowing the marker we append), so we reject such input up front.
    """
    masked = mask(code)
    depth = 0
    for c in masked.text:
        if c in "([{":
            depth += 1
        elif c in ")]}" and depth > 0:
            depth -= 1
    return depth > 0 or masked.ends_in_string


# M2 error reports begin with a location like ``stdio:3:8:(3):[1]: error:``
# or ``/path/Classic.m2:2:10:(3):[9]: error:``. Requiring that shape avoids
# false positives from ordinary output that merely contains the word "error".
_M2_ERROR_RE = re.compile(r"^[^\s:][^:]*:\d+:\d+:.*\berror\b", re.MULTILINE)


def contains_m2_error(text: str) -> bool:
    """True if ``text`` contains a M2 error report line."""
    return _M2_ERROR_RE.search(text) is not None


def split_logical_inputs(code: str) -> list[str]:
    """Split ``code`` into M2 logical inputs, for stop-on-error sending.

    A split happens at a newline only when the accumulated text is balanced
    (bracket depth 0, outside string literals). Blank and comment-only lines
    never complete a logical input in pipe mode (they dangle and absorb the
    next line), so they attach to the following statement instead — matching
    M2's own grouping.

    Known limitation (documented in the server's instructions): M2's parser
    has more continuation cases than this scanner models (e.g. a line ending
    mid-modifier like ``f_``); keep lines self-contained when using
    stop_on_error — the scanner errs toward NOT splitting (a glued chunk is
    recoverable, a wrongly split one changes semantics). Trailing
    blank/comment lines (uncompletable) are dropped.
    """
    masked = mask(code).text
    chunks: list[str] = []
    current: list[str] = []
    depth = 0
    in_str = False
    line_has_content = False
    i, n = 0, len(code)
    while i < n:
        line_start = i
        while i < n and code[i] != "\n":
            c = masked[i]
            if c == '"':
                in_str = not in_str
                line_has_content = True
            elif c in "([{":
                depth += 1
                line_has_content = True
            elif c in ")]}":
                depth = max(0, depth - 1)
                line_has_content = True
            elif not c.isspace():
                line_has_content = True
            i += 1
        i += 1  # consume the newline
        current.append(code[line_start : i - 1])
        completes = not _DANGLING_RE.search(masked[line_start : i - 1])
        if line_has_content and depth == 0 and not in_str and completes:
            chunks.append("\n".join(current))
            current = []
            line_has_content = False
    # Anything left unflushed is a run of blank/comment lines (content at
    # depth 0 flushes, and unbalanced code is rejected before splitting by
    # ends_unbalanced). It would dangle in M2, so it is dropped.
    return chunks


@dataclass
class EvalResult:
    output: str
    timed_out: bool = False
    crashed: bool = False
    interrupted: bool = False
    errored: bool = False  # block contains an M2 error report
    stopped: bool = False  # stop_on_error: later inputs were NOT sent
    not_sent: int = 0  # number of inputs skipped by stopping
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
        self._busy = False

    # ------------------------------------------------------------------ setup

    def interrupt(self) -> bool:
        """Send SIGINT to the kernel if (and only if) a computation is running.

        Lock-free by design: called from another coroutine while ``evaluate()``
        awaits M2 output. M2's default interrupt handling aborts the current
        input at a safe checkpoint and returns to the prompt; state defined by
        earlier completed statements survives. Verified on M2 1.26.06.

        Returns True if a signal was sent, False if nothing was running.
        """
        if not self._busy or self._proc is None or self._proc.returncode is not None:
            return False
        try:
            self._proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            return False
        logger.info("sent SIGINT to the M2 kernel")
        return True

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
            await self._marker_handshake(
                marker, STARTUP_TIMEOUT_S, write=(self._marker_stmt(marker) + "\n").encode()
            )
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

    @staticmethod
    def _marker_stmt(marker: str) -> str:
        # A COMPLETE statement that produces no oN= result and does NOT touch
        # M2's oo/ooo output history (verified on 1.26.06): scanning the empty
        # list is balanced (can't dangle) and evaluates to void.
        return f"scan({{}}, i -> {marker})"

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
        """Write ``write`` (which must end with the marker statement) and read
        until the marker line.

        The marker ``scan({}, i -> m2MCP<hex>)`` echoes (``iN : scan(...)``,
        or indented if a dangling last line absorbed it) and prints no result
        line, so the marker echo is the single boundary: everything printed
        before it is the answer to the preceding code. Matching is on the
        unique marker TEXT (not the ``iN :`` prefix) so absorbed echoes still
        terminate the read. Raises asyncio.TimeoutError or KernelCrashed.
        """
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(write)
        await self._proc.stdin.drain()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        # ends with "<marker>)" (absorbed or own echo line); marker text is unique
        marker_re = re.compile(rf"\b{re.escape(marker)}\)[ \t]*\r?$")
        index_re = re.compile(r"^i(\d+) :")
        lines: list[str] = []
        while True:
            text = await self._read_line(deadline)
            m = index_re.match(text)
            if m:
                self._prompt_index = max(self._prompt_index, int(m.group(1)))
            if marker_re.search(text):
                return "".join(lines)
            if _BARE_PROMPT_RE.match(text):
                # artifact of a SIGINT received while M2 waited for input
                continue
            lines.append(text)

    async def _send_and_wait(self, code: str, marker: str, timeout_s: float) -> str:
        """Send ``code`` followed by the marker statement.

        Returns the block printed before the marker's echo. Raises
        asyncio.TimeoutError or KernelCrashed.
        """
        payload = (code + "\n" + self._marker_stmt(marker) + "\n").encode("utf-8")
        return await self._marker_handshake(marker, timeout_s, write=payload)

    # ------------------------------------------------------------- evaluate

    async def evaluate(
        self, code: str, timeout_s: float = DEFAULT_TIMEOUT_S, *, stop_on_error: bool = False
    ) -> EvalResult:
        """Evaluate M2 code in the persistent session.

        With ``stop_on_error=False`` (the default) the code is sent as one
        submission and behaves like a human at the REPL: an error in one
        input does NOT prevent later inputs from running (M2 has no
        rollback). With ``stop_on_error=True`` the code is split into
        logical inputs and sent one at a time; on the first error the
        remaining inputs are NOT sent.

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
            if stop_on_error:
                return await self._evaluate_stopping(code, timeout_s)
            return await self._evaluate_whole(code, timeout_s)

    async def _attempt(self, code: str, timeout_s: int) -> tuple[str | None, EvalResult | None]:
        """Send one submission and wait for its marker handshake.

        Returns (block, None) on success, or (None, EvalResult) when a
        timeout/crash path already produced the final result.
        """
        marker = self._new_marker()
        logger.debug("evaluating %d chars of M2 code (timeout %ds)", len(code), timeout_s)
        self._busy = True
        try:
            block = await self._send_and_wait(code, marker, timeout_s)
        except asyncio.CancelledError:
            # The client cancelled this call: ask M2 to stop too (graceful,
            # keeps state) and let the cancellation propagate.
            self.interrupt()
            raise
        except asyncio.TimeoutError:
            logger.warning("evaluation timed out after %ds; restarting kernel", timeout_s)
            await self._kill()
            return None, EvalResult(output=_session_timeout_message(timeout_s), timed_out=True)
        except KernelCrashed as exc:
            logger.warning("kernel crashed: %s; restarting", exc)
            await self._kill()
            return None, EvalResult(
                output=(
                    f"ERROR: the Macaulay2 kernel exited unexpectedly ({exc}). "
                    f"The session was restarted.\n"
                    "Please retry your computation; if it fails again, the code "
                    "may be triggering a kernel bug (try a smaller input or "
                    "m2_run_script in an isolated process)."
                ),
                crashed=True,
            )
        finally:
            self._busy = False
        return block, None

    async def _finalize_block(self, block: str) -> EvalResult:
        """Post-process a successful continue-mode block."""
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
                errored=True,
            )
        output = block.strip()
        if not output:
            output = "(the code ran successfully and produced no output)"
        # stderr is merged in-stream, so an m2_interrupt shows up as
        # "error: interrupted" inside `block`.
        interrupted = "error: interrupted" in block
        if interrupted:
            output += (
                "\n\nNOTE: the computation was stopped on request "
                "(m2_interrupt). Everything defined by statements that "
                "completed before the interrupted one is still available; "
                "the session is ready for new input."
            )
        return EvalResult(
            output=output,
            interrupted=interrupted,
            errored=contains_m2_error(block) and not interrupted,
        )

    async def _evaluate_whole(self, code: str, timeout_s: int) -> EvalResult:
        block, early = await self._attempt(code, timeout_s)
        if early is not None:
            return early
        assert block is not None
        return await self._finalize_block(block)

    async def _evaluate_stopping(self, code: str, timeout_s: int) -> EvalResult:
        chunks = split_logical_inputs(code)
        if not chunks:
            return EvalResult(output="(empty input; nothing was evaluated)")
        collected: list[str] = []
        for idx, chunk in enumerate(chunks):
            remaining = len(chunks) - idx - 1
            block, early = await self._attempt(chunk, timeout_s)
            if early is not None:
                early.not_sent = remaining if early.timed_out or early.crashed else 0
                return early
            assert block is not None
            if "syntax error" in block:
                # parse-level desync risk is global: reuse the resync path
                early = await self._finalize_block(block)
                early.not_sent = remaining
                return early
            stripped = block.strip()
            if stripped:
                collected.append(stripped)
            if contains_m2_error(block):
                interrupted = "error: interrupted" in block
                text = "\n\n".join(collected) if collected else "(no output before the error)"
                return EvalResult(
                    output=text,
                    errored=True,
                    stopped=True,
                    interrupted=interrupted,
                    not_sent=remaining,
                )
        text = "\n\n".join(collected).strip()
        if not text:
            text = "(the code ran successfully and produced no output)"
        return EvalResult(output=text)

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
