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
* Separate statements with NEWLINES, not semicolons: with "A; B" on one line
  only the result of B is auto-printed.
* gb I returns a GroebnerBasis object; to SEE the basis polynomials use
  `print generators (gb I)`.
* res I computes a graded free resolution; `betti res I` prints the Betti table.
* Ring elements print with superscripts in plain text (e.g. `x^2` may show as a
  raised 2); parse accordingly.
* M2 strings use DOUBLE quotes ("..."), not single quotes.
* In m2_run_script (batch mode), only explicit `print` output is shown.
* `help "topic"` works in-session via the m2_help tool.

Timeouts: m2_evaluate and m2_run_script are guarded by an author-set default of
120 seconds to protect against runaway or infinite computations. If a call
returns a TIMED OUT message, the computation was still running (no M2 error);
retry with a larger timeout_s, and make the retried code self-contained (after
a session timeout the session is restarted, so include ring/ideal setup again).
For very long jobs, write code to a file and use m2_run_script instead.
"""


def _escape_m2_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_server() -> MCPServer:
    server = MCPServer(
        name="macaulay2",
        title="Macaulay2",
        version=__version__,
        description=(
            "Persistent Macaulay2 1.26 session: evaluate M2 code, inspect "
            "results, load packages, import local .m2 files, and run "
            "self-contained scripts."
        ),
        instructions=INSTRUCTIONS,
    )

    session = M2Session()
    runner = M2ScriptRunner()

    @server.tool()
    async def m2_evaluate(code: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> str:
        """Evaluate Macaulay2 code in the persistent session and return its output.

        State (rings, variables, ideals, ...) persists across calls. M2 errors
        are included in the returned text and do not break the session.
        Separate statements with newlines (with "A; B" on one line, only B's
        result is auto-printed).

        Args:
            code: Macaulay2 code, e.g. "R = QQ[x,y,z]\nI = ideal(x^3 - y,
                x^4 - z)\nprint generators (gb I)"
            timeout_s: Author-set safety limit (default 120, max 3600). Raise
                it for heavy computations (large Groebner bases, Hilbert
                polynomials, ...). On timeout the session is restarted, so the
                retried code must include all setup again.
        """
        result = await session.evaluate(code, timeout_s)
        return result.output

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
        operation). Use reload=True to re-read an already-loaded package from
        disk (e.g. after updating your M2 installation).

        Args:
            name: Package name as it appears on the M2 search path, e.g.
                "HilbertSchemes", "CommutativeAlgebra", "BoijSoederberg".
            reload: Force re-loading from disk even if already loaded.
        """
        safe = _escape_m2_string(name.strip())
        code = f'loadPackage "{safe}"'
        result = await session.evaluate(code)
        if "not reloaded; try Reload => true" in result.output and not reload:
            logger.info("package %s already loaded; retrying with Reload => true", name)
            result = await session.evaluate(f'loadPackage "{safe}", Reload => true')
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
