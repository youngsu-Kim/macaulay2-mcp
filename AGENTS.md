# AGENTS.md — working on macaulay2-mcp

## What this is

An MCP (Model Context Protocol) server exposing a persistent Macaulay2 1.26
session as tools. Python, `uv`-managed. Entry point: `macaulay2-mcp`
(console script) → `src/macaulay2_mcp/cli.py`.

## Commands

```sh
uv sync                      # install/refresh deps
uv run pytest -q             # full test suite (needs M2 1.26 installed)
uv run ruff check src tests  # lint
uv run macaulay2-mcp selftest# one-command install verification
uv run macaulay2-mcp         # run the MCP server on stdio
```

## Hard constraints (do not break)

1. **Stdio discipline:** when running as an MCP server, stdout carries the
   JSON-RPC protocol. NEVER print to stdout from server code — logging goes
   to stderr (`logging` is already configured that way). `selftest` may use
   stdout (it is not a server).
2. **M2 protocol — marker handshake:** M2 in pipe mode prints NO bare prompt
   while stdin stays open; it prints `iN : <input>` only together with the
   next input. M2's errors go to its **stderr**, which we merge into stdout
   at the OS level (`stderr=STDOUT`) so error text keeps true stream order
   in the returned output — do NOT separate them again (async drains race).
   Completion of an evaluation is detected by the two-step random marker in
   `kernel.py` (`m2MCP<12hex> = 1`: wait for the echo `iN : <marker> = 1`,
   then consume the deterministic result `oN = 1`). Blank or comment-only
   lines do NOT terminate a logical M2 input (they dangle and absorb the
   next line). Keep the marker a *complete statement* — never a comment.
3. **Golden outputs:** `tests/data/golden.jsonl` pins observable M2 1.26
   behaviour (rendering quirks included). If M2 output changes, review the
   dataset deliberately instead of letting it rot.
4. **Version pin:** v0.1 supports M2 1.26.x only (`config.py`). Do not add
   version branches; that's a v0.2 item.
5. **Timeouts are author-set safety limits** (default 120s, max 3600s).
   Timeout messages must keep saying it is NOT an M2 error and that the
   session was restarted (state lost → retry self-contained).
6. **No new user-facing config knobs** in v0.1 beyond `M2_BIN`. Pinned flags
   live in `config.py` (`M2_KERNEL_FLAGS`).

## Layout

```
src/macaulay2_mcp/
  config.py   binary discovery, version gate, pinned flags/timeouts
  kernel.py   M2Session (persistent kernel), M2ScriptRunner (batch), messages
  server.py   the 7 MCP tools + INSTRUCTIONS (LLM-facing, keep accurate)
  cli.py      entry point: server mode | selftest | --version
tests/
  test_kernel.py    protocol tests (skip if M2 1.26 missing)
  test_mcp_client.py client-level tests over stdio
e2e/                Docker + Ollama + opencode demo (opt-in: run_e2e.sh)
```

## M2 1.26 idioms relevant to this codebase

* `gb I` returns a GroebnerBasis; see polynomials via `print generators (gb I)`.
* A trailing `;` SUPPRESSES a statement's result display (`betti G;` prints
  nothing); `A; B` on one line shows only B. Use newlines + explicit `print`.
* M2 strings use double quotes; single quotes are invalid.
* `unloadPackage` and `importFile` do not exist in 1.26 — package "unload" =
  session reset; file import = evaluate the file's contents (m2_import_file).
* Preloaded packages error with "not reloaded; try Reload => true";
  `m2_load_package` turns that into an "already loaded" note and NEVER
  force-reloads — M2's own reload machinery breaks on packages whose source
  has dependency `needsPackage` lines (verified with PrimaryDecomposition).
  `reload=true` is the caller's explicit opt-in for that fragile path.
