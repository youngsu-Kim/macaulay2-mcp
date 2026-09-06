# macaulay2-mcp

Use [Macaulay2](https://macaulay2.com) from your AI coding assistant.

`macaulay2-mcp` is an [MCP](https://modelcontextprotocol.io) (Model Context Protocol)
server that gives Claude Code, [opencode](https://opencode.ai), Claude Desktop,
Gemini CLI, and any other MCP client a **persistent Macaulay2 session**: ask
your assistant to compute Groebner bases, resolutions, Betti tables, primary
decompositions, Hilbert polynomials — and it runs the computations in a real
M2 kernel, with state (rings, ideals, your definitions) preserved across calls.

```text
you   > compute the Groebner basis of ideal(x^3 - y, x^4 - z) in QQ[x,y,z],
        and a free resolution with Betti table
AI    > m2_evaluate: R = QQ[x,y,z]; I = ideal(x^3 - y, x^4 - z)
        m2_evaluate: print generators (gb I)
        m2_evaluate: G = res I; betti G
        The Groebner basis is {xy - z, x^2 z - y^2, y^3 - x z^2, x^3 - y}
        and the total Betti numbers are (1, 4, 4, 1).
```

---

## 30-second setup

**Prerequisites (one line each):**

| You need | macOS | Ubuntu |
|---|---|---|
| Macaulay2 (latest stable, 1.26) | `brew install macaulay2` | `sudo add-apt-repository ppa:macaulay2/macaulay2 && sudo apt install macaulay2` |
| [uv](https://docs.astral.sh/uv/) (runs the server, no install) | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

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
* **Gemini CLI** — `gemini mcp add macaulay2 -- uvx macaulay2-mcp` (or add an
  `mcpServers` entry to `~/.gemini/settings.json`).

`uvx` downloads and runs the server in an isolated environment on first use —
there is nothing else to install, and no configuration required.

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

With the server connected, just ask (in Claude Code / opencode / ...). These
are real tested prompts; the exact outputs are in
[`examples/example-prompts.md`](examples/example-prompts.md):

* “Create `R = QQ[x,y,z]` and `I = ideal(x^3 - y, x^4 - z)`. Compute the
  Groebner basis and a graded free resolution; show the Betti table.”
* “What are the dimensions of `R` and of `R/I`?” *(→ `3` and `1`: the monomial
  curve is a curve)*
* “Load the `BoijSoederberg` package and decompose the Betti diagram of
  `res I` into pure diagrams (`decomposeBetti`).”
* “Look up the documentation for `hilbertPolynomial` and compute it for the
  twisted cubic `(x*z - y^2, y*w - z^2, x*w - y*z)`.” *(→ `3T + 1`. Note the
  lowercase `h`: M2's CamelCase doc pointer `HilbertPolynomial` is an empty
  stub.)*
* “Compute the primary decomposition of `ideal(x^2, x*y)`.”
* “Here is my `mycode.m2` file — import it into the session and call
  `myFunction`.” (state is kept between calls)

A full genuine transcript of the first prompt:
[`examples/groebner-demo.md`](examples/groebner-demo.md).

## What the server provides

Eight tools, one shared M2 session:

| Tool | What it does |
|---|---|
| `m2_evaluate(code, timeout_s?)` | Evaluate M2 code in the persistent session. State carries over between calls. |
| `m2_interrupt()` | Stop a running computation: M2 aborts at a safe checkpoint and **keeps** all earlier definitions (unlike a timeout, which restarts the kernel). |
| `m2_session_reset()` | Restart the kernel — a clean slate. |
| `m2_help(topic)` | M2 documentation lookup (`help "topic"`). |
| `m2_run_script(path, timeout_s?)` | Run a `.m2` file in a fresh, isolated M2 process (batch mode; use `print` for output). |
| `m2_list_packages()` | List packages currently loaded in the session. |
| `m2_load_package(name, reload?)` | Load a package (e.g. `HilbertSchemes`, `CommutativeAlgebra`). |
| `m2_import_file(path)` | Import a local `.m2` file into the session — newly defined or updated commands are picked up without a restart. |

## How it works (and the safety limits)

The server keeps one Macaulay2 kernel alive and sends your code to it, exactly
like Emacs does. Results, M2 errors, and warnings all come back in the tool
output, so your assistant can read and react to them.

* **Version pin.** v0.1 supports **Macaulay2 1.26.x (latest stable) only**.
  Other versions produce a clear error with the upgrade command.
* **Timeout guard.** `m2_evaluate` and `m2_run_script` are guarded by an
  author-set default of **120 seconds** (raise per call up to 3600) against
  runaway or infinite computations. A timeout is *not* an M2 error: the
  message says so, and explains how to retry with a larger `timeout_s`
  (self-contained code, since the session is restarted).
* **Stopping on demand.** `m2_interrupt` sends a real software interrupt
  (SIGINT): M2 aborts the current computation at a safe checkpoint and the
  running call returns with `error: interrupted` — **all earlier definitions
  survive**. Only the timeout backstop (for computations that ignore the
  interrupt) restarts the kernel and loses state.
* **Unbalanced input** (e.g. a missing `}`) is rejected up front instead of
  hanging, and syntax errors that desynchronize the session trigger an
  automatic restart.
* **Security.** This is a local tool: your assistant can run arbitrary M2
  code on your machine (M2 code can in turn touch files and run system
  commands). Both Claude Code and opencode ask for your approval per tool
  call by default — keep it that way.

## Installing Macaulay2 (details)

| OS | Command |
|---|---|
| macOS (Homebrew) | `brew install macaulay2` |
| Ubuntu (official M2 PPA — always latest) | `sudo add-apt-repository ppa:macaulay2/macaulay2 && sudo apt install macaulay2` |
| Fedora | `sudo dnf install Macaulay2` (or the [M2 repo](https://macaulay2.com/Repositories/Fedora/)) |
| Debian stable | [M2 website repo](https://macaulay2.com/Repositories/Debian/) (distro version is older; v0.1 needs 1.26) |
| Anything else | <https://macaulay2.com/Downloads/> |

If M2 lives in a non-standard place, set `M2_BIN=/path/to/M2` in the client's
environment for the server.

## Try it in your browser (no install)

[![Launch on Binder](https://mybinder.org/badge.svg)](https://mybinder.org/v2/gh/YOUR-USERNAME/m2-mcp-binder/main?urlpath=lab/tree/demo.ipynb)

The companion repo [`m2-mcp-binder`](https://github.com/YOUR-USERNAME/m2-mcp-binder)
launches a JupyterLab session (first launch ~2–4 min) where a plain Python
notebook drives this very server over MCP — a zero-install way to see the
tools in action.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `selftest` says *Macaulay2 was not found* | Install M2 (table above) or set `M2_BIN`. |
| *Found Macaulay2 1.22.05, but ... only supports 1.26.x* | Upgrade: `brew upgrade macaulay2` or `sudo apt update && sudo apt install macaulay2` (with the M2 PPA added). |
| Server doesn't appear in the client | Restart the client; run `uvx macaulay2-mcp selftest` manually to see errors; check `claude mcp list` (Claude Code) or `opencode mcp list` (opencode). |
| A computation times out | Retry with a larger `timeout_s` (ask your assistant to), or write a script and use `m2_run_script`. To cancel a running computation while keeping session state, have the assistant call `m2_interrupt`. |
| Something about an unbalanced `}` | Your (or the assistant's) code was missing a closing bracket — the error message says so; just fix and resend. |

## Roadmap

* **v0.2** — remote/HTTP mode (Streamable HTTP + API key) so the server can be
  hosted and connected to **ChatGPT** and **Gemini Enterprise**; deployment
  recipes (Docker, Cloudflare Tunnel).
* **v1.0** — after community feedback: multi-user sessions, support for
  older/newer M2 versions, MCP prompts for common workflows (e.g. “analyze an
  ideal”), a package availability search, and more.

## Feedback

Please file issues and PRs on
[GitHub](https://github.com/YOUR-USERNAME/m2_mcp_project), and/or say hello on
the [Macaulay2 Zulip](https://macaulay2.zulipchat.com/) or
[Google group](https://groups.google.com/group/macaulay2).

## License

[MIT](LICENSE)
