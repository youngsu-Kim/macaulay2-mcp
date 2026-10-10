# macaulay2-mcp

## Motivation

The goal for the Macaulay2-MCP project is to leverage large-language-models when working with [Macaulay2](https://macaulay2.com). Especially, it should lower the entry point for newcomers or test a few lines of code. It is still under development and the code needs to be fully reviewed. Use it at your own risk and share your thoughts with me.

The current version is **under testing**. This early version is published on GitHub to test other components such as PyPI, LM Studio linking, and Binder.

## Philosophy

- Nearly all commands and programs below are non-invasive and reversible.
- The program is not designed to make decisions but inform the users of options.
- At some point, this MCP should work together with Lean-LSP.
- It will be updated on an as-needed basis.

## Acknowledgments

The project is largely developed under the author's guidance by Qwen 3.8 models hosted at [National Research Platform](https://nrp.ai). Also, the author thanks Dr. Mary Thomas and other leaders at the San Diego Supercomputer Center. The author learned a large portion of the skills used in this project from their CyberInfrastructure Professional Development Training Program.

## Introduction

Use [Macaulay2](https://macaulay2.com) from your AI coding assistant.

`macaulay2-mcp` is an [MCP](https://modelcontextprotocol.io) (Model Context Protocol) server that gives Claude Code, [opencode](https://opencode.ai), [LM Studio](https://lmstudio.ai), and any other MCP client a **persistent Macaulay2 session**: ask your assistant to compute Groebner bases, resolutions, Betti tables, primary decompositions, Hilbert polynomials — and it runs the computations in a real M2 kernel, with state (rings, ideals, your definitions) preserved across calls.

```text
you   > Compute a Groebner basis of the ideal $I = (x^3 - y, x^4 - z)$ in
        $\mathbb{Q}[x,y,z]$, and a free resolution of $S/I$ with Betti table
AI    > m2_evaluate: R = QQ[x,y,z]; I = ideal(x^3 - y, x^4 - z)
        m2_evaluate: print generators (gb I)
        m2_evaluate: G = res I; betti G
        The Groebner basis is {xy - z, x^2 z - y^2, y^3 - x z^2, x^3 - y}
        and the total Betti numbers are (1, 4, 4, 1).
```

M2 syntax helps weak models, LaTeX/plain math usually suffices for strong ones — your assistant does the translating; verify its input lines.

---

## 30-second setup

**Prerequisites (one line each):**

| You need | macOS | Ubuntu |
|---|---|---|
| Macaulay2 (latest stable, 1.26) | `brew install Macaulay2/tap/macaulay2` | `sudo add-apt-repository ppa:macaulay2/macaulay2 && sudo apt install macaulay2` |
| [uv](https://docs.astral.sh/uv/) (runs the server, no install) | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

On macOS the official uv script (`curl -LsSf https://astral.sh/uv/install.sh | sh`, installing to `~/.local/bin`) works equally well — snippets below use plain `uvx`, so either install route is fine.

Both commands add a package repository maintained by the Macaulay2 developers (a Homebrew *tap* / an APT *PPA*) — needed because `macaulay2` is not in Homebrew core and Ubuntu's own package is outdated. Recent Homebrew versions ask to *trust* a third-party tap before installing from it; trust entries live in `~/.homebrew/trust.json` and are reversible at any time: `brew untrust --tap Macaulay2/tap` (drop trust), `brew untap Macaulay2/tap` (remove the tap entirely, after `brew uninstall macaulay2`), or `sudo add-apt-repository --remove ppa:macaulay2/macaulay2` (PPA).

**Add it to your AI client (harness):**

* **Claude Code**
  ```sh
  claude mcp add macaulay2 -- uvx macaulay2-mcp
  ```
* **opencode** — add to your `opencode.json` (or project `opencode.json`):
  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "macaulay2": {
        "type": "local",
        "command": ["uvx", "macaulay2-mcp"]
      }
    }
  }
  ```
* **Claude Desktop** — add to `claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "macaulay2": {
        "command": "uvx",
        "args": ["macaulay2-mcp"]
      }
    }
  }
  ```
* **LM Studio (GUI chat)** — LM Studio (≥ 0.3.17) is itself an MCP host: [![Add MCP Server macaulay2 to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](lmstudio://add_mcp?name=macaulay2&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJtYWNhdWxheTItbWNwIl0sImVudiI6eyJNQUNBVUxBWTJfTUNQX0pPVVJOQUwiOiJ%2BLy5sb2NhbC9zaGFyZS9tYWNhdWxheTItbWNwL2pvdXJuYWxzIn19) or Program tab → **Install → Edit mcp.json** → paste, then enable the server and pick a **tool-calling-capable** model.
  ```json
  {
    "mcpServers": {
      "macaulay2": {
        "command": "uvx",
        "args": ["macaulay2-mcp"],
        "env": { "MACAULAY2_MCP_JOURNAL": "~/.local/share/macaulay2-mcp/journals" }
      }
    }
  }
  ```
  
  The `env` line just pins the history file to a known folder — see [Reading the journal](docs/journal.md) to relocate or turn it off. Setup details and fixes: [Troubleshooting](docs/troubleshooting.md).

**Check that everything is wired up:**

```sh
uvx macaulay2-mcp selftest
```

```text
macaulay2-mcp 0.1.4 self-test

[OK] found Macaulay2: /opt/homebrew/bin/M2
[OK] supported version (1.26.x): 1.26.06
[OK] started session: prompt received
[OK] evaluated 1 + 1: 1 + 1 / o1 = 2

Self-test passed. The MCP server is ready to use.
```

## Examples

With the server connected, just ask (in Claude Code / opencode / ...). All of these are tested prompts:

* “Create `R = QQ[x,y,z]` and `I = ideal(x^3 - y, x^4 - z)`. Compute the Groebner basis and a graded free resolution; show the Betti table.”
* “What are the dimensions of `R` and of `R/I`?” *(→ `3` and `1`: the monomial curve is a curve)*
* “Load the `BoijSoederberg` package and decompose the Betti diagram of `res I` into pure diagrams (`decomposeBetti`).”
* “Look up the documentation for `hilbertPolynomial` and compute it for the twisted cubic `(x*z - y^2, y*w - z^2, x*w - y*z)`.” *(→ `3T + 1`. Note the lowercase `h`: M2's CamelCase doc pointer `HilbertPolynomial` is an empty stub.)*
* “Compute the primary decomposition of `ideal(x^2, x*y)`.”
* “Work through Macaulay2's official *Getting Started* examples — the rational quartic `monomialCurveIdeal(R,{1,3,4})`: dimension, degree, Hilbert polynomial, resolution, Betti table.” *(straight from the [tutorial itself](https://macaulay2.com/GettingStarted/); it works over MCP unchanged)*
* “For the family `I_k = (x^(k+2) - y, x^(k+3) - z)` in `QQ[x,y,z]`, loop over `k = 1..6` and tabulate the reduced Groebner basis sizes and the dimensions of `R/I_k`.”
* “Same family, but fan the work out across several subagents as independent batch jobs and collect the results.” *(real parallel M2 processes)*
* “Here is my `mycode.m2` file — import it into the session and call `myFunction`.” (state is kept between calls)

A full genuine transcript of the first prompt: [`examples/groebner-demo.md`](examples/groebner-demo.md). How the server itself handles long runs, stops, parallel batches, and errors: [`examples/example-prompts.md`](examples/example-prompts.md) (§§2–5).

Want to benchmark your own model the way a real user types math? [`examples/latex-decomposition-test.md`](examples/latex-decomposition-test.md) gives you two ready prompts, a rubric with known-true answers, and what we measured.

### From your own code (no LLM required)

The server is an ordinary MCP stdio process, so plain Python can drive the same persistent kernel: [`examples/drive_with_python.py`](examples/drive_with_python.py) (`uv run python examples/drive_with_python.py`) shows state surviving between separate tool calls, times each call client-side, and reports kernel memory two ways — the per-call resident/peak line and the on-demand `m2_memory()` tool, with a computation that visibly moves the peak.

## What the server provides

Nine tools, one shared M2 session:

| Tool | What it does |
|---|---|
| `m2_evaluate(code, timeout_s?, stop_on_error?, show_memory?)` | Evaluate M2 code in the persistent session. State carries over between calls; `stop_on_error=True` halts at the first error instead of running the rest. Results end with a kernel-memory line (resident + peak; swap when paging) unless `show_memory=False`. |
| `m2_interrupt()` | Stop a running computation: M2 aborts at a safe checkpoint and **keeps** all earlier definitions (unlike a timeout, which restarts the kernel). |
| `m2_memory()` | Report the kernel's resident memory (RSS), peak, swap, pid, and uptime — an unprivileged OS read of the server's own child process; works **while** a computation runs, so you can watch before deciding to interrupt. |
| `m2_session_reset()` | Restart the kernel — a clean slate. |
| `m2_help(topic)` | M2 documentation lookup (`help "topic"`). |
| `m2_run_script(path, timeout_s?)` | Run a `.m2` file in a fresh, isolated M2 process (batch mode; use `print` for output). |
| `m2_list_packages()` | List packages currently loaded in the session. |
| `m2_load_package(name, reload?)` | Load a package (e.g. `HilbertSchemes`, `CommutativeAlgebra`). |
| `m2_import_file(path)` | Import a local `.m2` file into the session — newly defined or updated commands are picked up without a restart. |

## How it works (and the safety limits)

The server keeps one Macaulay2 kernel alive and sends your code to it, exactly like Emacs does. Results, M2 errors, and warnings all come back in the tool output, so your assistant can read and react to them.

* **Version pin.** v0.1 supports **Macaulay2 1.26.x (the current latest stable at release time) only**. Other versions produce a clear error with the upgrade command.
* **Timeout guard.** `m2_evaluate` and `m2_run_script` are guarded by an author-set default of **120 seconds** (raise per call up to 3600) against runaway or infinite computations. A timeout is *not* an M2 error: the message says so, and explains how to retry with a larger `timeout_s` (self-contained code, since the session is restarted).
* **Stopping on demand.** `m2_interrupt` sends a real software interrupt (SIGINT): M2 aborts the current computation at a safe checkpoint and the running call returns with `error: interrupted` — **all earlier definitions survive**. Only the timeout backstop (for computations that ignore the interrupt) restarts the kernel and loses state.
* **Parallelism.** The shared session serializes evaluations by design (one kernel = consistent state; safe for concurrent requests from subagents). Genuine concurrency today: every `m2_run_script` spawns its own M2 process and multiple jobs run in parallel — e.g. one subagent per slice of an ideal family. First-class job submission (`m2_submit_job`, status/wait/cancel over a kernel pool) is planned.
* **Errors inform, they don't decide.** M2 is a REPL: a runtime error does *not* stop the remaining lines from running, and there is no rollback. When that happens, the tool result appends an explicit menu — CONTINUE (fix and resend just the failing statement), RESTART (session reset — irreversible, all definitions lost), or INSPECT (see what survived) — and your assistant is instructed to put those choices to *you*. To prevent the cascade up front, run blocks with `stop_on_error=True`.
* **Unbalanced input** (e.g. a missing `}`) is rejected up front instead of hanging, and syntax errors that desynchronize the session trigger an automatic restart.
* **OS-access gate.** M2 functions that run programs, touch the filesystem, reach the network, or kill the kernel (`runProgram`, `lines`, `openOut`, `makeDirectory`, `installPackage`, `quit`, …) are **refused before anything executes** — the session stays untouched and the message explains how the user can enable a specific symbol (`MACAULAY2_MCP_OS_ALLOW=lines,openOut` in the server's environment). The gate is friction against accidents, not a sandbox: M2's `value("...")` string-evaluation is not blocked (blocking it breaks legitimate metaprogramming). For real isolation, run the server in a container/VM.
* **Audit journal.** Every MCP↔M2 exchange is appended to a JSONL file at `./.m2-mcp/session-<UTC>-<pid>.jsonl` in your project: the code, M2's output, timings, refused gate attempts, and the MCP client (LLM host) that connected. Relocate with `MACAULAY2_MCP_JOURNAL=<dir>`, disable with `=off`; for GUI clients a single central location is recommended, e.g. `~/.local/share/macaulay2-mcp/journals`. Add `.m2-mcp/` to your `.gitignore` (the server never reads it back in v0.1; checkpoint/replay is planned). Full guide: [Reading the journal](docs/journal.md).
* **Long results are excerpted.** A tool result past ~120 lines / 32 KB comes back as its first 100 and last 10 lines with a notice naming where the full text was saved (the journal); nothing is silently lost, and chats stay readable. Prefer narrowing in M2 (`take`, `drop`, smaller examples) over dumping huge results.
* **Memory reporting.** Every `m2_evaluate` result ends with the kernel's resident memory and its peak — pass `show_memory=False` to omit that line — and `m2_memory()` answers on demand, *including while a long computation is running* (a cheap watchdog: watch, then decide whether `m2_interrupt` is worthwhile). When the kernel starts paging to swap, the line names the swap amount and a note lays out the options; nothing is ever killed automatically. The journal records `rss_bytes`, `peak_rss_bytes` and `swap_bytes` per evaluation regardless of the flag, and a kernel killed by a timeout is probed just before the restart, so its last measurement survives. Peak uses kernel-tracked counters (`VmHWM` on Linux; `footprint`'s `phys_footprint_peak` on macOS), not sampling; swap is per-process on Linux, and the system-wide growth since the kernel started on macOS (Apple exposes no unprivileged per-process swap counter).
* **Security.** This remains a local tool: your assistant can run arbitrary M2 computation on your machine. Both Claude Code and opencode ask for your approval per tool call by default — keep it that way.

### Tested environments

Behaviour (including the golden outputs) is pinned against Macaulay2 1.26 on:

| Environment | Machine | Memory relevant to the swap guidance |
|---|---|---|
| Development | Apple-silicon Mac, macOS 27 | — |
| CI | GitHub Actions ubuntu-latest | 16 GB |
| Binder demo | Container / hosted VM | Low single-digit GB, host-dependent |

### The OS-access gate

Why some perfectly normal-looking code is **blocked**, and where this safeguard's honest limits are: the full rationale lives in [`docs/os-access-gate.md`](docs/os-access-gate.md). In one line: M2 functions that run programs, touch the filesystem, reach the network, or kill the kernel are refused *before anything executes* — and since the check matches words rather than call positions, a plain variable named `lines` is refused too (rename it, or allowlist the symbol via `MACAULAY2_MCP_OS_ALLOW`). It is friction against accidents, not a sandbox.

## Design principles

1. **Local-first.** The server runs on your machine against your Macaulay2 installation. No accounts, no telemetry, no network calls.
2. **Messages inform, never direct.** Every message states what it does and whether (and how) it is reversible; we explain decisions instead of telling you to click through them.
3. **Errors carry their own fix.** "Not found" ships with install commands; "wrong version" ships with the exact upgrade line; timeouts explain the retry recipe.
4. **Safety limits are explicit.** Timeouts are author-set, labeled as such, distinguishable from real errors, and adjustable per call.

## Installing Macaulay2 (details)

| OS | Command |
|---|---|
| macOS (Homebrew) | `brew install Macaulay2/tap/macaulay2` (the tap also exposes `M2` as an alias; `brew trust Macaulay2/tap` first on very recent Homebrew) |
| Ubuntu (official M2 PPA — always latest) | `sudo add-apt-repository ppa:macaulay2/macaulay2 && sudo apt install macaulay2` |
| Windows | Not supported in v0.1 (macOS and Ubuntu are the tested platforms; WSL2 untested) |

If M2 lives in a non-standard place, set `M2_BIN=/path/to/M2` in the client's environment for the server. The only other settings are `MACAULAY2_MCP_JOURNAL` (journal location / `off`, see [Reading the journal](docs/journal.md)) and `MACAULAY2_MCP_OS_ALLOW` (comma-separated M2 OS-symbols to unblock); v0.1 intentionally has no others.

## Try it in your browser (no install)

[![Launch on Binder](https://mybinder.org/badge.svg)](https://mybinder.org/v2/gh/youngsu-Kim/macaulay2-mcp-binder/main?urlpath=lab/tree/demo.ipynb)

The companion repo [`m2-mcp-binder`](https://github.com/youngsu-Kim/macaulay2-mcp-binder) launches a JupyterLab session (first launch ~2–4 min) where a plain Python notebook drives this very server over MCP — a zero-install way to see the tools in action.

## Troubleshooting

Symptoms and fixes: [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Todos/Plans

* Remote/HTTP mode (Streamable HTTP + API key) so the server can be hosted and connected to services such as ChatGPT web; deployment recipes (Docker, Cloudflare Tunnel).
* Multi-user sessions, support for older/newer M2 versions, MCP prompts for common workflows (e.g. "analyze an ideal"), a package availability search, and more — after community feedback.
* Session-state persistence across restarts.
* Dedicated dataset to train an LLM.

## Feedback

Please file issues and PRs on [GitHub](https://github.com/youngsu-Kim/macaulay2-mcp). Once the software has stabilized, it is expected to be announced in the [Macaulay2 Zulip](https://macaulay2.zulipchat.com/) first.

## License

This program is free software under the [GNU General Public License v3 or later](LICENSE): use it freely, including commercially — but if you distribute it, or a program built on top of it, the same freedoms must travel with your copy.
