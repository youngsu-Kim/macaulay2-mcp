"""The macaulay2 MCP server: tools exposing a persistent Macaulay2 session."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from mcp.server import MCPServer

from . import __version__
from .config import DEFAULT_TIMEOUT_S
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

    @server.tool()
    async def m2_evaluate(
        code: str, timeout_s: int = DEFAULT_TIMEOUT_S, stop_on_error: bool = False
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
        return text

    @server.tool()
    async def m2_interrupt() -> str:
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
        if session.interrupt():
            return (
                "Interrupt sent (SIGINT). If the computation is interruptible, "
                "the running m2_evaluate will return shortly with an "
                "'error: interrupted' note and the session keeps all earlier "
                "definitions."
            )
        return "Nothing is running in the Macaulay2 session; nothing to interrupt."

    @server.tool()
    async def m2_session_reset() -> str:
        """Restart the Macaulay2 kernel, discarding ALL session state.

        Use before starting a fresh line of computation, or whenever the
        session seems corrupted. After a reset, rings and definitions from
        earlier calls no longer exist.
        """
        return await session.reset()

    @server.tool()
    async def m2_help(topic: str) -> str:
        """Look up Macaulay2 documentation for a function, class, or concept.

        Args:
            topic: Documentation entry point, e.g. "groebnerBasis",
                "resolution", "HilbertPolynomial", "Package".
        """
        safe = _escape_m2_string(topic.strip())
        result = await session.evaluate(f'help "{safe}"', timeout_s=60)
        return result.output

    @server.tool()
    async def m2_run_script(path: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> str:
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
        result = await runner.run(path, timeout_s)
        text = result.output or "(the script produced no output)"
        if result.exit_code not in (0, None):
            text += f"\n\n(exit code {result.exit_code})"
        return text

    @server.tool()
    async def m2_list_packages() -> str:
        """List the Macaulay2 packages currently loaded in the session.

        Returns the package names, e.g.
        {Varieties, Complexes, PrimaryDecomposition, Core, ...}.
        """
        result = await session.evaluate("loadedPackages")
        return result.output

    @server.tool()
    async def m2_load_package(name: str, reload: bool = False) -> str:
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
        if reload:
            result = await session.evaluate(f'loadPackage "{safe}", Reload => true')
            return result.output
        result = await session.evaluate(f'loadPackage "{safe}"')
        if "not reloaded; try Reload => true" in result.output:
            pkg = name.strip()
            return (
                f"Package {pkg!r} is already loaded in this session; nothing "
                f"to do. (Pass reload=true only if you edited the package "
                f"source and need it re-read from disk.)"
            )
        return result.output

    @server.tool()
    async def m2_import_file(path: str) -> str:
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
        result = await session.evaluate(content)
        return (
            result.output
            + f"\n\n(imported {len(content.splitlines())} lines from {path})"
        )

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
