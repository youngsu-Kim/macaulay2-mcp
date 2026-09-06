# E2E: opencode + local LLM + macaulay2 MCP server (Docker)

End-to-end demonstration and regression check: a small **local** LLM
(Ollama) drives **opencode**, which calls the `macaulay2` MCP server over
stdio; the server runs a real Macaulay2 1.26 kernel inside the container.
Everything runs on CPU — targeted at 16 GB RAM machines.

## Run it

```sh
docker compose up -d ollama          # or just:
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

## The demo task (`task.txt`)

Create `R = QQ[x,y,z]`, `I = ideal(x^3 - y, x^4 - z)`, compute the Groebner
basis and a graded free resolution with Betti table, and report both.

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
