"""Command-line entry point.

Usage:
    macaulay2-mcp            run the MCP server on stdio (default)
    macaulay2-mcp selftest   check the local Macaulay2 installation
    macaulay2-mcp --version  print the server version
"""

from __future__ import annotations

import asyncio
import sys

from . import __version__


def _check(label: str, ok: bool, detail: str = "", hint: str = "") -> bool:
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not ok and hint:
        print(hint, file=sys.stderr)
    return ok


def run_selftest() -> int:
    print(f"macaulay2-mcp {__version__} self-test")
    print()

    from .config import (
        M2NotFoundError,
        M2StartupError,
        UnsupportedM2Version,
        load_config,
    )

    try:
        config = load_config()
    except (M2NotFoundError, UnsupportedM2Version, M2StartupError) as exc:
        print(f"[FAIL] locating Macaulay2:\n{exc}")
        return 1

    if not _check("found Macaulay2", True, detail=config.binary):
        return 1
    if not _check("supported version (1.26.x)", True, detail=config.version_str):
        return 1

    from .kernel import M2Session

    session = M2Session(config)

    async def probes() -> int:
        try:
            try:
                await session.ensure_started()
            except Exception as exc:  # noqa: BLE001 - report anything
                _check("started session", False, detail=str(exc))
                return 1
            _check("started session", True, detail="prompt received")
            result = await session.evaluate("1 + 1")
        finally:
            await session.close()
        ok = not result.timed_out and not result.crashed and "2" in result.output
        if not _check("evaluated 1 + 1", ok, detail=result.output.strip()):
            return 1
        print()
        print("Self-test passed. The MCP server is ready to use.")
        return 0

    return asyncio.run(probes())


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("--version", "-V"):
        print(__version__)
        return 0
    if args and args[0] == "selftest":
        return run_selftest()
    if args:
        # Unknown arguments: report on stderr and never pollute stdout, which
        # is the MCP protocol channel when running as a server.
        print("usage: macaulay2-mcp [selftest | --version]", file=sys.stderr)
        return 2
    from .server import serve_stdio

    serve_stdio()
    return 0


if __name__ == "__main__":
    sys.exit(main())
