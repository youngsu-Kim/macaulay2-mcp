#!/usr/bin/env python3
"""Drive the macaulay2-mcp server from plain Python — no LLM involved.

The server is an ordinary MCP stdio process, so your own code can use it
exactly the way Claude Code or opencode does. This script demonstrates three
things the current server reports per call:

  * persistence  — a second, separate m2_evaluate uses the ring and ideal
                   defined in the FIRST call (the persistent-kernel property
                   a Jupyter kernel gives you; here over MCP),
  * wall time    — timed client-side around each tool call,
  * memory       — every m2_evaluate result ends with the kernel's
                   resident/peak line (suppress with show_memory=False), and
                   the m2_memory() tool answers with exact bytes on demand,
                   including after forcing the kernel to grow.

Run it (Macaulay2 1.26 on PATH):

    uv run python examples/drive_with_python.py

To point it at a checkout of this repo instead of the published package, set:

    SERVER = StdioServerParameters(
        command="uv",
        args=["--directory", "/path/to/macaulay2-mcp", "run", "macaulay2-mcp"],
    )

The Binder demo notebook uses this same pattern inside Jupyter (it needs one
extra trick there — a background-thread event loop — because Jupyter kernels
already own one).

Genuine condensed output (macOS, published 0.1.4 via uvx — full run lives in
this script):

    connected — server exposes 9 tools: m2_evaluate, m2_interrupt, m2_memory, ...
    [1] define the ring and an ideal (one call)
        (M2 memory: 118.3 MB resident, peak 103.0 MB)   wall time: 1.84 s
    [2] SEPARATE call reuses R and I from call 1 (persistent state)
        | xy-z x2z-y2 y3-xz2 x3-y |
        (M2 memory: 118.5 MB resident, peak 103.0 MB)   wall time: 0.04 s
    [4] force the kernel to grow: expand (x+y+z)^300
        (M2 memory: 321.4 MB resident, peak 306.0 MB)   wall time: 0.43 s
    [4b] m2_memory() again — note the peak move
        M2 kernel memory: 321.4 MB resident (337018880 bytes), peak 306.0 MB
"""

import asyncio
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command="uvx", args=["macaulay2-mcp"])


async def call(session: ClientSession, tool: str, **args) -> str:
    result = await session.call_tool(tool, args)
    return result.content[0].text


async def timed(session: ClientSession, tool: str, **args):
    start = time.perf_counter()
    text = await call(session, tool, **args)
    return text, time.perf_counter() - start


def clip(text: str, keep: int = 3) -> str:
    """Show the first `keep` lines plus the trailing memory-report line."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) <= keep + 1:
        return "\n".join("    " + line for line in lines)
    skipped = len(lines) - keep - 1
    shown = lines[:keep] + [f"... {skipped} line(s) omitted ...", lines[-1]]
    return "\n".join("    " + line for line in shown)


async def demo() -> None:
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"connected — server exposes {len(tools)} tools:")
            print(f"    {', '.join(tools)}\n")

            print("[1] define the ring and an ideal (one call)")
            out, dt = await timed(
                session,
                "m2_evaluate",
                code="R = QQ[x,y,z]\nI = ideal(x^3 - y, x^4 - z)",
            )
            print(clip(out))
            print(f"    wall time: {dt:.2f} s\n")

            print("[2] SEPARATE call reuses R and I from call 1 (persistent state)")
            out, dt = await timed(
                session,
                "m2_evaluate",
                code="print generators (gb I)\ndim (R/I)",
            )
            print(clip(out))
            print(f"    wall time: {dt:.2f} s\n")

            print("[3] m2_memory() on demand (exact bytes)")
            print(clip(await call(session, "m2_memory")))
            print()

            print("[4] force the kernel to grow: expand (x+y+z)^300")
            out, dt = await timed(session, "m2_evaluate", code="F = (x+y+z)^300;")
            print(f"    {out.strip().splitlines()[-1]}")
            print(f"    wall time: {dt:.2f} s")
            print("[4b] m2_memory() again — note the peak move")
            print(clip(await call(session, "m2_memory")))


if __name__ == "__main__":
    asyncio.run(demo())
