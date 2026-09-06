# E2E: opencode + local LLM + macaulay2 MCP server (Docker)

End-to-end demonstration and regression check: a small **local** LLM
(Ollama) drives **opencode**, which calls the `macaulay2` MCP server over
stdio; the server runs a real Macaulay2 1.26 kernel inside the container.
Everything runs locally; the CPU path is targeted at 16 GB RAM machines.

## GPU modes (auto-detected, force with `E2E_OLLAMA_MODE=…`)

| mode | when chosen | what runs where |
|---|---|---|
| `native` | macOS + `ollama` on the host | Ollama runs **natively (Apple Silicon Metal)**; the agent container talks to `http://host.docker.internal:11434`. This is the GPU path on Macs: Docker containers on macOS run in a Linux VM **without Metal passthrough**, so a containerized Ollama can never use the Mac GPU. If host Ollama isn't running, the script stops and tells you (or set `E2E_OLLAMA_MODE=container`). |
| `gpu` | Linux with `nvidia-smi` | Ollama container with NVIDIA passthrough (`docker-compose.gpu.yml`, `gpus: all`). |
| `container` | otherwise | Ollama in Docker, CPU-only — works everywhere, slowest. |

```sh
./run_e2e.sh                                  # auto-detect, prints the chosen mode
E2E_OLLAMA_MODE=container ./run_e2e.sh        # force CPU container
E2E_MODEL=qwen3:4b ./run_e2e.sh               # native path uses your host Ollama's models
```

## Run it

```sh
./run_e2e.sh
```

`run_e2e.sh` builds the agent image (M2 1.26 via the official PPA, uv,
opencode — the image build itself runs `macaulay2-mcp selftest`), pulls the
model, runs the demo task up to `E2E_ATTEMPTS` (default 3) times, and
asserts on the `opencode run --format json` event log. Transcripts land in
`results/`.

```sh
E2E_MODEL=qwen3:8b E2E_ATTEMPTS=2 ./run_e2e.sh   # try another model
```

First run downloads the model (qwen3:4b ≈ 2.6 GB, qwen3:14b ≈ 9 GB).

## The demo tasks

* `task.txt` — asks for the same computation with explicit M2 syntax hints
  (`R = QQ[x,y,z]`, `I = ideal(x^3 - y, x^4 - z)`).
* `task-latex.txt` — the same job phrased the way a mathematician writes it:
  `Let $S = \mathbb{Q}[x,y,z]$ and $I = (x^3 - y, x^4 - z)$ ... list its
  elements ... Betti table of a free resolution of $S/I$`. No M2 syntax.

Swap prompts with `TASK_FILE=task-latex.txt ./run_e2e.sh`.
`soak.sh` cycles both tasks across several models for `SOAK_HOURS` hours and
appends one TSV row per cycle to `results/soak-summary.tsv` (it also removes
orphaned `e2e-*` containers between cycles; it kills nothing on the host).

## What the assertions check

The event log separates two responsibilities:

* **The server (deterministic, hard-checked):** the `m2_evaluate` tool
  results must contain the real computation — the Groebner basis
  (`xy - z`) and the Betti total row (`1 4 4 1`). If this fails, the server
  or the protocol is broken.
* **The model (best effort):** the final answer must report the Groebner
  basis. Faithfully transcribing the Betti row is *soft* (reported, not
  fatal) — small models compress tables.

## Reference results (2026-08-31, M2 1.26.06, 8-core CPU)

| model | attempts | result | final answer |
|---|---|---|---|
| qwen3:4b | 1/1 | PASS (incl. soft Betti check) | "Groebner basis polynomials: xy - z, x²z - y², y³ - xz², x³ - y / Total Betti numbers: 1 4 4 1" |
| qwen3:14b | 1/1 | PASS (incl. soft Betti check) | identical |

Both models issued a **single** well-formed `m2_evaluate` call
(`R=...; I=...; print generators (gb I); G = res I; print betti G;`).

Note: earlier runs (before the server instructions explicitly warned that a
trailing `;` suppresses a statement's result, and before `task.txt` said to
use `print betti G`) failed the Betti check 6/6 — the model sent
`betti G;`, M2 printed nothing, and the model hallucinated the numbers.
Lesson: for small models, encode M2's display rules in the tool
instructions, not just in the prompt.

## LaTeX-prompt reliability (soak, 2026-09-06, macOS Metal, M2 1.26.06)

49 cycles of `SOAK_HOURS=3 e2e/soak.sh` (1 attempt per cycle), all models
local via host Ollama:

| model | `task.txt` (M2 syntax) | `task-latex.txt` (plain math) |
|---|---|---|
| qwen3.5:4b | 7/8 | 0/9 |
| qwen3.6:27b | 8/8 | 0/8 |
| qwen3.8:27b | 8/8 | 0/8 |

What the transcripts show for the LaTeX task: **notation translation is
reliable** (every model correctly emitted `R = QQ[x,y,z]; I = ideal(x^3 - y,
x^4 - z)`), but the models then (a) drop one of the two sub-requests — the
Groebner listing failed in 24/25 runs, (b) chain statements on one line ending
in `;`, silently suppressing the table (17/25), and (c) answer from memory
instead of output when a display comes back empty (hallucinated totals).
These persist across 27B models and despite INSTRUCTIONS warnings against
each pattern.

Interpretation: with small/local models, say what you want in plain math **and**
keep the M2 commands in view (the `task.txt` style) — or verify the assistant's
input lines against the output. Frontier cloud models handle the LaTeX form
better, but we have not measured them.
