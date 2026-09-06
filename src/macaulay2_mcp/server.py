"""The macaulay2 MCP server: tools exposing a persistent Macaulay2 session."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from . import __version__
from .config import DEFAULT_TIMEOUT_S
from .gatekeep import check_package_name, find_blocked_calls, rejection_message
from .journal import Journal
from .kernel import M2ScriptRunner, M2Session

logger = logging.getLogger("macaulay2_mcp.server")

INSTRUCTIONS = """\
This server bridges to a persistent Macaulay2 1.26 session (the latest stable
release). State — rings, variables, ideals, matrices, loaded packages, user
definitions — persists across m2_evaluate calls within one session; use
m2_session_reset for a clean slate.

Macaulay2 1.26 idioms you will need:
* Separate statements with NEWLINES, not semicolons. A trailing ";" SUPPRESSES
  that statement's result (e.g. "betti G;" prints nothing) — so to see a
  result either omit the ";" or use an explicit "print ...".
* gb I returns a GroebnerBasis object; to SEE the basis polynomials use
  `print generators (gb I)`.
* res I computes a graded free resolution; `betti res I` prints the Betti table.
* Ring elements print with superscripts in plain text (e.g. `x^2` may show as a
  raised 2); parse accordingly.
* M2 strings use DOUBLE quotes ("..."), not single quotes.
* Loop over a family with: for k from 1 to 5 list (I := ideal(...); <expr>)
  — ':=' scopes I locally per iteration. Trap: "I_k = ..." defines ONE
  symbol named I_k (underscore is a name character, not indexing); use a
  function instead: I = k -> ideal(...), then call it as I 3.
* State persists, which means old values haunt new rings: to reuse a name
  that currently holds a value as a plain symbol, reset it first, e.g.
  "a = symbol a" (the official tutorial does this with x).
* Documentation: use the m2_help tool — NOT M2's viewHelp (it opens a
  browser window; blocked by the OS gate).
* print takes one expression: print (a | b | c) — without parentheses,
  "print a | b" parses as (print a) | b. Concatenate strings with '|'.
* In m2_run_script (batch mode), only explicit `print` output is shown.
* `help "topic"` works in-session via the m2_help tool.

Timeouts: m2_evaluate and m2_run_script are guarded by an author-set default of
120 seconds to protect against runaway or infinite computations. If a call
returns a TIMED OUT message, the computation was still running (no M2 error);
retry with a larger timeout_s, and make the retried code self-contained (after
a session timeout the session is restarted, so include ring/ideal setup again).
For very long jobs, write code to a file and use m2_run_script instead.

Stopping: if the user wants to cancel a still-running computation, call
m2_interrupt — M2 aborts the current input at a safe checkpoint, the running
m2_evaluate returns with "error: interrupted", and all earlier definitions
stay available. (A timeout, by contrast, kills and restarts the kernel and
loses session state.)

Errors: M2 is a REPL — a runtime error in one statement does NOT stop the
rest of your code from running (later inputs execute, possibly on broken
assumptions), and there is no rollback: even a failing line like "x = 2;
bogusFn(x)" leaves x = 2 defined. When a result reports an error, the server
appends options (continue / restart / inspect) — present them to the user
instead of choosing silently. To prevent cascades, send multi-statement
blocks with stop_on_error=True: statements are then submitted one at a time
(every line must be self-contained: end each statement fully; do not break
a line after a binary operator) and everything after the first error is not
executed. Note the asymmetry: m2_run_script runs in M2's batch mode with
--stop, so a script halts at its first error by design.

OS-access gate: before anything runs, this server REFUSES code that mentions
M2's operating-system functions (runProgram, findProgram, lines, openIn,
openOut, makeDirectory, installPackage, quit, and similar process/file/
network/env symbols). Nothing is executed and the session is untouched when
this happens. Relay the BLOCKED message to the user; if they want such a
call, THEY can enable specific symbols via the MACAULAY2_MCP_OS_ALLOW
environment variable. Do not attempt to route around the gate (e.g. via
value("...")) — flag it to the user instead and let them decide.

Parallelism: the shared session serializes concurrent m2_evaluate calls by
design (one kernel, cooperating state). For independent heavy work — e.g.
computing invariants for a whole family I_k — prefer self-contained
m2_run_script jobs: each runs in its own M2 process and several run truly
in parallel (issue them as parallel tool calls, or fan out across host
subagents, each handling a slice of the family).
"""


def _escape_m2_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


_ERROR_OPTIONS_NOTE = """NOTE(macaulay2-mcp): M2 reports an error above, but as a \
REPL, it did NOT halt — inputs after the failing line already ran (possibly on \
broken assumptions), and M2 has no rollback for partial state (a failed line \
like "x = 2; bogusFn(x)" still leaves x = 2 defined). Before retrying, ask the \
user how to proceed:
  (1) CONTINUE — resend only the corrected failing statement, plus any later \
statements that failed because of it; re-check anything computed after the error.
  (2) RESTART — m2_session_reset, then rerun a corrected, self-contained block. \
This is irreversible: ALL current session definitions are lost.
  (3) INSPECT — evaluate the affected names first to see what survived.
To prevent cascades on the next attempt, resend with stop_on_error=True \
(inputs after the first error will not be executed)."""


_STOPPED_ADDENDUM = """NOTE(macaulay2-mcp): the run halted at the failing input \
(stop_on_error): {not_sent} later input(s) were NOT executed. M2 has no \
rollback, so the failing line's earlier statements took effect (e.g. \
"x = 2; bogusFn(x)" leaves x = 2 defined). Before retrying, ask the user how \
to proceed:
  (1) CONTINUE — resend the corrected failing statement followed by the \
unexecuted remainder.
  (2) RESTART — m2_session_reset, then rerun the corrected block in full. \
This is irreversible: ALL current session definitions are lost.
  (3) INSPECT — evaluate the affected names first to see what survived."""


def _gate_file(path: str) -> str | None:
    """Read a .m2 file and return a rejection message if it uses OS symbols.

    Returns None (proceed) when the file is unreadable or not text — the
    downstream runner/importer produce the appropriate error in that case.
    """
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    blocked = find_blocked_calls(content)
    if blocked:
        return "\n".join(rejection_message(sym) for sym in blocked)
    return None


def _client_info(ctx: Context | None) -> dict | None:
    """Best-effort extraction of the connected client's identity (clientInfo
    from the MCP initialize handshake) for the journal header."""
    if ctx is None:
        return None
    try:
        rc = ctx.request_context
        params = rc.session.client_params
        if params is None or params.client_info is None:
            return None
        ci = params.client_info
        return {
            "name": ci.name,
            "title": getattr(ci, "title", None),
            "version": ci.version,
            "protocol_version": rc.protocol_version,
        }
    except Exception:  # noqa: BLE001 - never let introspection break a tool call
        return None


def build_server() -> MCPServer:
    server = MCPServer(
        name="macaulay2",
        title="Macaulay2",
        version=__version__,
        description=(
            "Persistent Macaulay2 1.26 session: evaluate M2 code, interrupt "
            "running computations, inspect results, load packages, import "
            "local .m2 files, and run self-contained scripts."
        ),
        instructions=INSTRUCTIONS,
    )

    session = M2Session()
    runner = M2ScriptRunner()
    journal = Journal.from_env(__version__)
    if journal.enabled and journal.path is not None:
        logger.info("journal: %s", journal.path)
        # NOTE: no record() here — the header line is written lazily on the
        # first tool call so it can carry clientInfo from the initialize
        # handshake (set_client_info runs before every record).

    @server.tool()
    async def m2_evaluate(
        code: str,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        stop_on_error: bool = False,
        ctx: Context = None,
    ) -> str:
        """Evaluate Macaulay2 code in the persistent session and return its output.

        State (rings, variables, ideals, ...) persists across calls. M2 errors
        are included in the returned text and do not break the session.
        Separate statements with newlines: a trailing ";" suppresses that
        statement's result (use an explicit "print" to force output).

        Args:
            code: Macaulay2 code, e.g. "R = QQ[x,y,z]\nI = ideal(x^3 - y,
                x^4 - z)\nprint generators (gb I)"
            timeout_s: Author-set safety limit (default 120, max 3600). Raise
                it for heavy computations (large Groebner bases, Hilbert
                polynomials, ...). On timeout the session is restarted, so the
                retried code must include all setup again.
            stop_on_error: Default False = REPL semantics (an error does not
                stop later lines from running). True sends the code input by
                input and halts at the first error, leaving later inputs
                unexecuted. Requires each line to be a self-contained
                statement (do not break a line after a binary operator).
        """
        blocked = find_blocked_calls(code)
        if blocked:
            journal.set_client_info(_client_info(ctx))
            journal.record("os_block", tool="m2_evaluate", symbols=blocked, code=code)
            return "\n".join(rejection_message(sym) for sym in blocked)
        t0 = time.perf_counter()
        result = await session.evaluate(code, timeout_s, stop_on_error=stop_on_error)
        text = result.output
        if result.errored and not result.interrupted and not result.crashed:
            text += "\n\n" + (
                _STOPPED_ADDENDUM.format(not_sent=result.not_sent)
                if result.stopped
                else _ERROR_OPTIONS_NOTE
            )
        elif result.not_sent and not result.crashed:
            text += f"\n\n(stop_on_error: {result.not_sent} later input(s) were not executed.)"
        journal.set_client_info(_client_info(ctx))
        journal.record(
            "evaluate",
            code=code,
            timeout_s=timeout_s,
            stop_on_error=stop_on_error,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            timed_out=result.timed_out,
            crashed=result.crashed,
            interrupted=result.interrupted,
            errored=result.errored,
            stopped=result.stopped,
            not_sent=result.not_sent,
            m2=session.describe(),
            output=text,
        )
        return text

    @server.tool()
    async def m2_interrupt(ctx: Context = None) -> str:
        """Interrupt the Macaulay2 computation currently running in the session.

        Use this when the user wants to cancel or stop a long-running
        m2_evaluate. It sends a software interrupt (SIGINT), which M2
        handles at safe checkpoints: the running m2_evaluate call returns
        with an "error: interrupted" message, and everything defined by
        statements that completed BEFORE the interrupted one stays
        available — the session does not restart.

        If nothing is running, this is a harmless no-op. In the rare case
        of a computation that ignores the interrupt (deep engine loops),
        the running m2_evaluate's own timeout_s remains the backstop: it
        kills and restarts the kernel on expiry.
        """
        sent = session.interrupt()
        journal.set_client_info(_client_info(ctx))
        journal.record("interrupt", sent=sent)
        if sent:
            return (
                "Interrupt sent (SIGINT). If the computation is interruptible, "
                "the running m2_evaluate will return shortly with an "
                "'error: interrupted' note and the session keeps all earlier "
                "definitions."
            )
        return "Nothing is running in the Macaulay2 session; nothing to interrupt."

    @server.tool()
    async def m2_session_reset(ctx: Context = None) -> str:
        """Restart the Macaulay2 kernel, discarding ALL session state.

        Use before starting a fresh line of computation, or whenever the
        session seems corrupted. After a reset, rings and definitions from
        earlier calls no longer exist.
        """
        out = await session.reset()
        journal.set_client_info(_client_info(ctx))
        journal.record("reset", output=out)
        return out

    @server.tool()
    async def m2_help(topic: str, ctx: Context = None) -> str:
        """Look up Macaulay2 documentation for a function, class, or concept.

        Args:
            topic: Documentation entry point, e.g. "groebnerBasis",
                "resolution", "HilbertPolynomial", "Package".
        """
        safe = _escape_m2_string(topic.strip())
        result = await session.evaluate(f'help "{safe}"', timeout_s=60)
        journal.set_client_info(_client_info(ctx))
        journal.record("help", topic=topic, output=result.output)
        return result.output

    @server.tool()
    async def m2_run_script(
        path: str, timeout_s: int = DEFAULT_TIMEOUT_S, ctx: Context = None
    ) -> str:
        """Run a .m2 file in a FRESH, isolated Macaulay2 process.

        Does not touch the persistent session (and its state is not visible
        afterwards). Use for long or self-contained computations, or when a
        repeated m2_evaluate timeout suggests a heavy job. This is batch mode:
        only explicit `print` output is returned — the script must print its
        own results.

        Args:
            path: ABSOLUTE path to the .m2 file, e.g. "/tmp/compute.m2".
            timeout_s: Author-set safety limit (default 120, max 3600). On
                timeout the process is killed and any partial output is
                returned.
        """
        gate = _gate_file(path)
        journal.set_client_info(_client_info(ctx))
        if gate is not None:
            journal.record("os_block", tool="m2_run_script", path=path, detail=gate)
            return gate
        t0 = time.perf_counter()
        result = await runner.run(path, timeout_s)
        text = result.output or "(the script produced no output)"
        if result.exit_code not in (0, None):
            text += f"\n\n(exit code {result.exit_code})"
        journal.record(
            "run_script",
            path=path,
            timeout_s=timeout_s,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            output=text,
        )
        return text

    @server.tool()
    async def m2_list_packages(ctx: Context = None) -> str:
        """List the Macaulay2 packages currently loaded in the session.

        Returns the package names, e.g.
        {Varieties, Complexes, PrimaryDecomposition, Core, ...}.
        """
        result = await session.evaluate("loadedPackages")
        journal.set_client_info(_client_info(ctx))
        journal.record("list_packages", output=result.output)
        return result.output

    @server.tool()
    async def m2_load_package(name: str, reload: bool = False, ctx: Context = None) -> str:
        """Load a Macaulay2 package into the session.

        Packages stay loaded until the session is reset (M2 has no unload
        operation). Loading an already-loaded package is a harmless no-op:
        the tool reports that and changes nothing. Use reload=True ONLY when
        the package's source on disk changed and must be re-read (M2's
        reload machinery is fragile for packages with dependencies).

        Args:
            name: Package name as it appears on the M2 search path, e.g.
                "HilbertSchemes", "CommutativeAlgebra", "BoijSoederberg".
            reload: Re-read the package from disk even if already loaded
                (package-development workflow; leave False otherwise).
        """
        safe = _escape_m2_string(name.strip())
        journal.set_client_info(_client_info(ctx))
        path_err = check_package_name(name)
        if path_err is not None:
            journal.record("os_block", tool="m2_load_package", name=name, detail=path_err)
            return path_err
        if reload:
            result = await session.evaluate(f'loadPackage "{safe}", Reload => true')
            journal.record("load_package", name=name, reload=True, output=result.output)
            return result.output
        result = await session.evaluate(f'loadPackage "{safe}"')
        if "not reloaded; try Reload => true" in result.output:
            pkg = name.strip()
            out = (
                f"Package {pkg!r} is already loaded in this session; nothing "
                f"to do. (Pass reload=true only if you edited the package "
                f"source and need it re-read from disk.)"
            )
            journal.record("load_package", name=name, reload=reload, output=out)
            return out
        journal.record("load_package", name=name, reload=reload, output=result.output)
        return result.output

    @server.tool()
    async def m2_import_file(path: str, ctx: Context = None) -> str:
        """Import a local .m2 file INTO the persistent session.

        Reads the file and evaluates its contents in the session, so newly
        defined or updated functions/variables become available immediately —
        no session restart needed. This is the M2 equivalent of what Emacs
        does when you "load" a file into a running kernel. Re-importing
        re-defines the file's symbols.

        Args:
            path: ABSOLUTE path to the .m2 file to import.
        """
        file = Path(path)
        if not file.is_absolute():
            return f"ERROR: path must be absolute, got {path!r}."
        if not file.is_file():
            return f"ERROR: file not found: {path}"
        try:
            content = file.read_text(encoding="utf-8")
        except OSError as exc:
            return f"ERROR: could not read {path}: {exc}"
        if not content.strip():
            return f"(file {path} is empty; nothing imported)"
        blocked = find_blocked_calls(content)
        journal.set_client_info(_client_info(ctx))
        if blocked:
            journal.record("os_block", tool="m2_import_file", path=path, symbols=blocked)
            return "\n".join(rejection_message(sym) for sym in blocked)
        result = await session.evaluate(content)
        out = (
            result.output
            + f"\n\n(imported {len(content.splitlines())} lines from {path})"
        )
        journal.record("import_file", path=path, lines=len(content.splitlines()), output=out)
        return out

    return server


def configure_logging() -> None:
    # stdio servers must never write to stdout; all logging goes to stderr.
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def serve_stdio() -> None:
    configure_logging()
    server = build_server()
    server.run(transport="stdio")
