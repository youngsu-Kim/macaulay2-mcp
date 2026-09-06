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
   Completion of an evaluation is detected by the void marker in `kernel.py`
   (`scan({}, i -> m2MCP<12hex>)`: read until a line ending with the unique
   marker text). The marker must be a COMPLETE statement (blank/comment
   lines dangle and absorb the next line) AND produce no `oN` output —
   an assignment marker polluted M2's `oo`/`ooo` history, breaking the
   official tutorial's `4*5; oo` workflow (regression test:
   `test_oo_history_survives_calls`). Blank or comment-only lines do NOT
   terminate a logical M2 input. SIGINT (m2_interrupt) works in pipe mode:
   M2 prints `error: interrupted`, prompt indices stay in sync, the
   buffered marker still executes (the in-flight evaluate() returns
   normally), and state survives. SIGINT while idle only emits a bare
   `iN :` line — filtered from evaluation blocks.
   `M2Session.interrupt()` is LOCK-FREE by design (evaluate() holds the
   session lock while running); never make it take the lock.
3. **Golden outputs:** `tests/data/golden.jsonl` pins observable M2 1.26
   behaviour (rendering quirks included). If M2 output changes, review the
   dataset deliberately instead of letting it rot.
4. **Version pin:** v0.1 supports M2 1.26.x only (`config.py`). Do not add
   version branches; that's a later-version item.
5. **Timeouts are author-set safety limits** (default 120s, max 3600s).
   Timeout messages must keep saying it is NOT an M2 error and that the
   session was restarted (state lost → retry self-contained).
6. **Concurrency semantics are by design:** `m2_evaluate` serializes on the
   session lock (one shared kernel = consistent state; concurrent requests
   from subagents are safe, just queued), while `m2_run_script` takes no
   lock (each job is an independent M2 process — that IS the parallelism
   story until the planned job pool). Never "optimize away" the serialization.
   Tests and docs pin outputs, NEVER timings.
7. **No new user-facing config knobs.** The complete v0.1 set is `M2_BIN`
   (binary location), `MACAULAY2_MCP_JOURNAL` (journal dir / `off`), and
   `MACAULAY2_MCP_OS_ALLOW` (gate unblock list). Pinned flags and limits
   live in `config.py` (`M2_KERNEL_FLAGS`, timeouts).
8. **Messages inform, never direct.** Every user-facing string (install
   hints, errors, tool outputs, README) states what the suggested action
   does and whether it is reversible — and how to undo it. We do not tell
   users to blindly agree/answer yes; we explain the decision and leave it
   to them. Applies equally to LLM-facing text (INSTRUCTIONS, docstrings):
   the assistant relays information, not pressure.
9. **Error-continuation semantics are a pinned contract.** M2 continues
   running inputs after an error (no rollback; even mid-input side effects
   persist) — golden cases `error_then_continue`/`partial_input_effect` pin
   this. The continue/restart/inspect options NOTE is composed ONLY in the
   `m2_evaluate` handler for runtime errors (never for interrupted,
   restart, or timeout results, which have their own messages).
   `stop_on_error` uses `split_logical_inputs` (blank/comment lines attach
   forward; trailing uncompletable lines dropped; documented limitation:
   dangling trailing operators). `_marker_handshake` matches the marker
   TEXT anywhere in a line and tracks the index from any `iN :` line —
   do NOT re-anchor to `^iN : <marker>`: a code block ending in a comment
   absorbs the marker as a continuation line and the handshake would hang
   to timeout (regression test: `test_trailing_comment_does_not_swallow_marker`).
10. **Gate + journal contracts.** The OS-call gatekeeper (`gatekeep.py`)
    refuses process/file/network/env/session symbols BEFORE sending anything,
    at all four entry points (evaluate, run_script, import_file,
    load_package path check); it matches on `scanner.mask()` output —
    strings/comments never false-positive; `value()` is deliberately NOT
    blocked (documented bypass; friction not sandbox). The journal
    (`journal.py`) defaults ON at `./.m2-mcp/`, writes lazily so the header
    carries clientInfo (via `ctx.request_context.session.client_params` —
    SDK v2 stdio path), truncates fields at 1 MiB, and MUST NEVER raise into
    a tool call (self-disables with one stderr warning) and never touches
    stdout. Tool handlers take a hidden `ctx: Context = None` param — the SDK
    excludes it from the JSON schema; keep that pattern.

## Layout

```
src/macaulay2_mcp/
  config.py    binary discovery, version gate, pinned flags/timeouts
  scanner.py   offset-preserving string/comment mask (shared by kernel+gate)
  kernel.py    M2Session (persistent kernel), M2ScriptRunner (batch), messages
  gatekeep.py  OS-call blocklist + rejection messages (mask-based matching)
  journal.py   JSONL audit journal (lazy header w/ clientInfo, never raises)
  server.py    the 8 MCP tools + INSTRUCTIONS (LLM-facing, keep accurate)
  cli.py       entry point: server mode | selftest | --version
tests/
  test_kernel.py     protocol tests (skip if M2 1.26 missing)
  test_gatekeep.py   masking / enforcement / live blocking
  test_journal.py    journal units + live clientInfo-in-header round trip
  test_mcp_client.py client-level tests over stdio
e2e/                 Docker + Ollama + opencode demo (opt-in: run_e2e.sh)
```

## M2 1.26 idioms relevant to this codebase

* `gb I` returns a GroebnerBasis; see polynomials via `print generators (gb I)`.
* A trailing `;` SUPPRESSES a statement's result display (`betti G;` prints
  nothing); `A; B` on one line shows only B. Use newlines + explicit `print`.
* Family loops: `for k from 1 to n list (J := ideal(...); <expr>)` with `:=`
  for per-iteration locals. `I_k = ...` is ONE symbol named "I_k", not
  indexing. `print (a | b)` needs parens — `print a | b` is `(print a) | b`.
* M2 strings use double quotes; single quotes are invalid.
* `unloadPackage` and `importFile` do not exist in 1.26 — package "unload" =
  session reset; file import = evaluate the file's contents (m2_import_file).
* Preloaded packages error with "not reloaded; try Reload => true";
  `m2_load_package` turns that into an "already loaded" note and NEVER
  force-reloads — M2's own reload machinery breaks on packages whose source
  has dependency `needsPackage` lines (verified with PrimaryDecomposition).
  `reload=true` is the caller's explicit opt-in for that fragile path.
