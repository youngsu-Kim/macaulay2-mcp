# macaulay2-mcp

## Why?

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

Both commands add a package repository maintained by the Macaulay2 developers (a Homebrew *tap* / an APT *PPA*) — needed because `macaulay2` is not in Homebrew core and Ubuntu's own package is outdated. Recent Homebrew versions ask to *trust* a third-party tap before installing from it; trust entries live in `~/.homebrew/trust.json` and are reversible at any time: `brew untrust --tap Macaulay2/tap` (drop trust), `brew untap Macaulay2/tap` (remove the tap entirely, after `brew uninstall macaulay2`), or `sudo add-apt-repository --remove ppa:macaulay2/macaulay2` (PPA).

**Then, one line for your client:**

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
  (If that doesn't work, use the absolute path from `which uvx`.)
* **Gemini CLI** — `gemini mcp add macaulay2 -- uvx macaulay2-mcp` (or add an `mcpServers` entry to `~/.gemini/settings.json`).
* **LM Studio (GUI chat)** — one-click "Add to LM Studio" button and setup in [Use it in a GUI](#use-it-in-a-gui-lm-studio-macos-apple-silicon).

`uvx` downloads and runs the server in an isolated environment on first use — there is nothing else to install, and no configuration required.

**Check that everything is wired up:**

```sh
uvx macaulay2-mcp selftest
```

```text
macaulay2-mcp 0.1.0 self-test

[OK] found Macaulay2: /opt/homebrew/bin/M2
[OK] supported version (1.26.x): 1.26.06
[OK] started session: prompt received
[OK] evaluated 1 + 1: 1 + 1 / o1 = 2

Self-test passed. The MCP server is ready to use.
```

## Try this now

With the server connected, just ask (in Claude Code / opencode / ...). These are real tested prompts; the exact outputs are in [`examples/example-prompts.md`](examples/example-prompts.md):

* “Create `R = QQ[x,y,z]` and `I = ideal(x^3 - y, x^4 - z)`. Compute the Groebner basis and a graded free resolution; show the Betti table.”
* “What are the dimensions of `R` and of `R/I`?” *(→ `3` and `1`: the monomial curve is a curve)*
* “Load the `BoijSoederberg` package and decompose the Betti diagram of `res I` into pure diagrams (`decomposeBetti`).”
* “Look up the documentation for `hilbertPolynomial` and compute it for the twisted cubic `(x*z - y^2, y*w - z^2, x*w - y*z)`.” *(→ `3T + 1`. Note the lowercase `h`: M2's CamelCase doc pointer `HilbertPolynomial` is an empty stub.)*
* “Compute the primary decomposition of `ideal(x^2, x*y)`.”
* “Work through Macaulay2's official *Getting Started* examples — the rational quartic `monomialCurveIdeal(R,{1,3,4})`: dimension, degree, Hilbert polynomial, resolution, Betti table.” *(see [`examples/official-tutorial-run.md`](examples/official-tutorial-run.md))*
* “For the family `I_k = (x^(k+2) - y, x^(k+3) - z)` in `QQ[x,y,z]`, loop over `k = 1..6` and tabulate the reduced Groebner basis sizes and the dimensions of `R/I_k`.”
* “Same family, but fan the work out across several subagents as independent batch jobs and collect the results.” *(real parallel M2 processes)*
* “Here is my `mycode.m2` file — import it into the session and call `myFunction`.” (state is kept between calls)

A full genuine transcript of the first prompt: [`examples/groebner-demo.md`](examples/groebner-demo.md).

## What the server provides

Eight tools, one shared M2 session:

| Tool | What it does |
|---|---|
| `m2_evaluate(code, timeout_s?, stop_on_error?)` | Evaluate M2 code in the persistent session. State carries over between calls; `stop_on_error=True` halts at the first error instead of running the rest. |
| `m2_interrupt()` | Stop a running computation: M2 aborts at a safe checkpoint and **keeps** all earlier definitions (unlike a timeout, which restarts the kernel). |
| `m2_session_reset()` | Restart the kernel — a clean slate. |
| `m2_help(topic)` | M2 documentation lookup (`help "topic"`). |
| `m2_run_script(path, timeout_s?)` | Run a `.m2` file in a fresh, isolated M2 process (batch mode; use `print` for output). |
| `m2_list_packages()` | List packages currently loaded in the session. |
| `m2_load_package(name, reload?)` | Load a package (e.g. `HilbertSchemes`, `CommutativeAlgebra`). |
| `m2_import_file(path)` | Import a local `.m2` file into the session — newly defined or updated commands are picked up without a restart. |

## How it works (and the safety limits)

The server keeps one Macaulay2 kernel alive and sends your code to it, exactly like Emacs does. Results, M2 errors, and warnings all come back in the tool output, so your assistant can read and react to them.

* **Version pin.** v0.1 supports **Macaulay2 1.26.x (latest stable) only**. Other versions produce a clear error with the upgrade command.
* **Timeout guard.** `m2_evaluate` and `m2_run_script` are guarded by an author-set default of **120 seconds** (raise per call up to 3600) against runaway or infinite computations. A timeout is *not* an M2 error: the message says so, and explains how to retry with a larger `timeout_s` (self-contained code, since the session is restarted).
* **Stopping on demand.** `m2_interrupt` sends a real software interrupt (SIGINT): M2 aborts the current computation at a safe checkpoint and the running call returns with `error: interrupted` — **all earlier definitions survive**. Only the timeout backstop (for computations that ignore the interrupt) restarts the kernel and loses state.
* **Parallelism.** The shared session serializes evaluations by design (one kernel = consistent state; safe for concurrent requests from subagents). Genuine concurrency today: every `m2_run_script` spawns its own M2 process and multiple jobs run in parallel — e.g. one subagent per slice of an ideal family. First-class job submission (`m2_submit_job`, status/wait/cancel over a kernel pool) is planned.
* **Errors inform, they don't decide.** M2 is a REPL: a runtime error does *not* stop the remaining lines from running, and there is no rollback. When that happens, the tool result appends an explicit menu — CONTINUE (fix and resend just the failing statement), RESTART (session reset — irreversible, all definitions lost), or INSPECT (see what survived) — and your assistant is instructed to put those choices to *you*. To prevent the cascade up front, run blocks with `stop_on_error=True`.
* **Unbalanced input** (e.g. a missing `}`) is rejected up front instead of hanging, and syntax errors that desynchronize the session trigger an automatic restart.
* **OS-access gate.** M2 functions that run programs, touch the filesystem, reach the network, or kill the kernel (`runProgram`, `lines`, `openOut`, `makeDirectory`, `installPackage`, `quit`, …) are **refused before anything executes** — the session stays untouched and the message explains how the user can enable a specific symbol (`MACAULAY2_MCP_OS_ALLOW=lines,openOut` in the server's environment). The gate is friction against accidents, not a sandbox: M2's `value("...")` string-evaluation is not blocked (blocking it breaks legitimate metaprogramming). For real isolation, run the server in a container/VM.
* **Audit journal.** Every MCP↔M2 exchange is appended to a JSONL file at `./.m2-mcp/session-<UTC>-<pid>.jsonl` in your project: the code, M2's output, timings, refused gate attempts, and the MCP client (LLM host) that connected. Relocate with `MACAULAY2_MCP_JOURNAL=<dir>`, disable with `=off`; for GUI clients a single central location is recommended, e.g. `~/.local/share/macaulay2-mcp/journals`. Add `.m2-mcp/` to your `.gitignore` (the server never reads it back in v0.1; checkpoint/replay is planned).
* **Security.** This remains a local tool: your assistant can run arbitrary M2 computation on your machine. Both Claude Code and opencode ask for your approval per tool call by default — keep it that way.

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
| Anything else | <https://macaulay2.com/Downloads/> |

If M2 lives in a non-standard place, set `M2_BIN=/path/to/M2` in the client's environment for the server. The only other settings are `MACAULAY2_MCP_JOURNAL` (journal location / `off`) and `MACAULAY2_MCP_OS_ALLOW` (comma-separated M2 OS-symbols to unblock); v0.1 intentionally has no others.

## Use it in a GUI: LM Studio (macOS, Apple Silicon)

[LM Studio](https://lmstudio.ai) (≥ 0.3.17) is itself an MCP host: add this server and **local models can call Macaulay2 straight from the chat window** — no terminal agent involved. This section targets **Apple Silicon Macs with Homebrew**; Intel Macs follow the same steps with `/usr/local` paths, and on Linux the CLI clients above are the documented route.

**Prerequisites (one line each):**
```sh
brew install Macaulay2/tap/macaulay2   # M2 1.26 (LM Studio's GUI env is minimal — see note)
brew install uv                        # provides /opt/homebrew/bin/uvx
```

**Install:** switch to the **Program** tab (right sidebar) → **Install → Edit mcp.json** → paste:

```json
{
  "mcpServers": {
    "macaulay2": {
      "command": "/opt/homebrew/bin/uvx",
      "args": ["macaulay2-mcp"],
      "env": { "MACAULAY2_MCP_JOURNAL": "~/.local/share/macaulay2-mcp/journals" }
    }
  }
}
```

[![Add MCP Server macaulay2 to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](https://lmstudio.ai/install-mcp?name=macaulay2&config=eyJjb21tYW5kIjoiL29wdC9ob21lYnJldy9iaW4vdXZ4IiwiYXJncyI6WyJtYWNhdWxheTItbWNwIl0sImVudiI6eyJNQUNBVUxBWTJfTUNQX0pPVVJOQUwiOiJ+Ly5sb2NhbC9zaGFyZS9tYWNhdWxheTItbWNwL2pvdXJuYWxzIn19)

Why the snippet looks different from the CLI ones (each choice is yours to change):

* **Absolute `/opt/homebrew/bin/uvx`** — GUI apps don't inherit your shell's PATH, so a bare `"uvx"` often fails to launch. (If you installed uv via the astral script instead of brew, use `~/.local/bin/uvx`.)
* **No `M2_BIN` needed** — the server looks for Macaulay2 in the standard Homebrew locations automatically, which is exactly what a minimal GUI PATH requires. Non-standard installs: add `"M2_BIN": "/path/to/M2"` to `env`.
* **Explicit `MACAULAY2_MCP_JOURNAL`** — GUI-launched servers have an unpredictable working directory, so the journal's default `./.m2-mcp/` would land somewhere mysterious; the snippet pins it to `~/.local/share/macaulay2-mcp/journals` (the XDG data standard — the server expands `~` to your home directory, and `rm -rf ~/.local/share/macaulay2-mcp` deletes everything the server ever wrote). `"MACAULAY2_MCP_JOURNAL": "off"` also works.

Then enable the server in the Program tab, pick a **tool-calling-capable** model, and try:

> Compute a Groebner basis of the ideal $I = (x^3 - y, x^4 - z)$ in $\mathbb{Q}[x,y,z]$ and print its elements.

You should see a `m2_evaluate` tool call in the chat's tool activity, then the basis. Honest caveat measured in our own Docker E2E: small local models vary a lot at tool calling and at transcribing tables — the server's built-in instructions, error menus, and output journal (LM Studio shows up there as the connected client) are designed to help weaker models, not rescue every case. If a computation is refused by the OS gate, the same `MACAULAY2_MCP_OS_ALLOW` env applies here.

> The install button and every `uvx macaulay2-mcp` command go live when the package is published to PyPI (v0.1.0); until then, from a checkout you can point the `command` at `uv` with `--directory /path/to/m2_mcp_project` and `["run", "macaulay2-mcp"]` as a preview.

## Try it in your browser (no install)

[![Launch on Binder](https://mybinder.org/badge.svg)](https://mybinder.org/v2/gh/youngsu-Kim/macaulay2-mcp-binder/main?urlpath=lab/tree/demo.ipynb)

The companion repo [`m2-mcp-binder`](https://github.com/youngsu-Kim/macaulay2-mcp-binder) launches a JupyterLab session (first launch ~2–4 min) where a plain Python notebook drives this very server over MCP — a zero-install way to see the tools in action.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `selftest` says *Macaulay2 was not found* | Install M2 (table above) or set `M2_BIN`. |
| *Found Macaulay2 1.22.05, but ... only supports 1.26.x* | Upgrade: `brew tap Macaulay2/tap && brew update && brew upgrade macaulay2` or `sudo apt update && sudo apt install macaulay2` (with the M2 PPA added). |
| Server doesn't appear in the client | Restart the client; run `uvx macaulay2-mcp selftest` manually to see errors; check `claude mcp list` (Claude Code) or `opencode mcp list` (opencode). |
| A computation times out | Retry with a larger `timeout_s` (ask your assistant to), or write a script and use `m2_run_script`. To cancel a running computation while keeping session state, have the assistant call `m2_interrupt`. |
| Something about an unbalanced `}` | Your (or the assistant's) code was missing a closing bracket — the error message says so; just fix and resend. |
| A `.m2-mcp/` folder appeared in your project | That is the audit journal (every M2 exchange, one JSONL file per server run). Add it to `.gitignore`, relocate with `MACAULAY2_MCP_JOURNAL=<dir>`, or disable with `MACAULAY2_MCP_JOURNAL=off`. |
| `BLOCKED: ... gatekeeper refuses '...'` | The assistant tried an M2 function that touches the OS (process/file/network). Nothing ran. If you trust the code, set `MACAULAY2_MCP_OS_ALLOW=<symbol>,<symbol>` in the server's environment and restart the client. |
| Server won't start in a GUI app (LM Studio, Claude Desktop) | GUI apps get a minimal PATH — use the **absolute** path to `uvx` (`which uvx` in a terminal) in the `command` field. For LM Studio you can watch the server's log in the Program tab's server detail view. |

## Todos/Plans

* Remote/HTTP mode (Streamable HTTP + API key) so the server can be hosted and connected to services such as ChatGPT web; deployment recipes (Docker, Cloudflare Tunnel).
* Multi-user sessions, support for older/newer M2 versions, MCP prompts for common workflows (e.g. "analyze an ideal"), a package availability search, and more — after community feedback.
* Memory track (persist and reuse session state across runs).
* Dedicated dataset to train an LLM.

## Feedback

Please file issues and PRs on [GitHub](https://github.com/youngsu-Kim/macaulay2-mcp). Once the software has stabilized, it is expected to be announced in the [Macaulay2 Zulip](https://macaulay2.zulipchat.com/) first.

## License

This program is free software under the [GNU General Public License v3 or later](LICENSE): use it freely, including commercially — but if you distribute it, or a program built on top of it, the same freedoms must travel with your copy.
