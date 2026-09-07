# bench — host-local model grid (what models can actually drive this server)

Companion to [`../e2e/`](../e2e/): e2e validates **the server** on macOS and
Linux (Docker); bench measures **the model side of the conversation**, running
entirely on the host — host opencode, host Ollama (Metal), host Macaulay2, this
repo's server. No Docker anywhere.

## The question

Users type math the way they write it on paper (LaTeX in a chat box). Does the
assistant translate, decompose the request, and verify against real output?
Two prompt variants isolate the levers:

* `task-a.txt` — a three-part LaTeX question ((a) Groebner basis listing,
  (b) Betti table, (c) dimension) + one grounding rule: "Do not answer anything
  you have not seen in a tool output."
* `task-b.txt` — the same plus explicit decomposition scaffolding (one
  `m2_evaluate` per part, verify each display, rerun on empty output because
  `;` suppresses).

## Results (2026-09-06, macOS, 3 attempts per cell)

All models at their default Ollama quantization, 4-bit `Q4_K_M`, pulled
2026-09-05/06; exact arch/params/context per model in `results/models.csv`.

| model (params) | raw (a) | scaffolded (b) | notes |
|---|---|---|---|
| gemma4:e2b (5.1B) | 0/3 | 0/3 | |
| gemma4:e4b (8.0B) | 0/3 | 1/3 | one full scaffolded pass |
| qwen3:4b (4.0B) | 0/3 | 0/3 | mostly 1-call early stops |
| qwen3.5:4b (4.7B) | 0/3 | 0/3 | high effort (7–12 calls) yet never finishes |
| qwen3:14b (14.8B) | 0/3 | 0/3 | |
| **qwen3.6:27b (27.3B)** | **3/3** | 1/3 | |
| **qwen3.8:27b (27.3B)** | 1/3 | **3/3** | |
| gemma4:12b (11.9B) | 0/3 | 0/3 |

## Findings

1. **Translation was never the failure.** In all 48 cells, every model
   converted the LaTeX notation to valid M2 syntax on its first tool call. No
   recorded failure had a mistranslation as its cause.
2. **No fabricated values.** No failing cell reported a number that had not
   appeared in a tool output. The dominant failure is abandonment: the run ends
   after one call, answering at most the first of three parts.
3. **Only the dense 27B models completed the 3-part task one-shot**, both at
   4 of 6: Qwen3.6-27B Q4_K_M (3/3 raw, 1/3 scaffolded) and Qwen3.8-27B
   Q4_K_M (1/3 raw, 3/3 scaffolded). All dense models at 11.9B and below,
   including Gemma4-12B Q4_K_M, scored 0-1/6.
4. **The scaffold changed outcomes by at most ±2/3 in either direction** on the
   two 27B models — within binomial noise at n=3. No conclusion about
   scaffolding is drawn from this grid; it is a regression baseline.
5. **The first scoring pass reported 0/42 and was wrong.** The dimension check
   matched only `dim ... = 1` lines and missed M2's bare value printing
   (`dim I` outputs `o7 : 1`). Fixed in `collect.py`; `rescore.py` re-scores
   all raw logs offline, so check changes never require re-running models.

This grid measures one-shot CLI runs only; multi-turn chat sessions (where a
user can say "continue") are not measured here.

## Patient-user probe (session resume, 2026-09-06)

One-shot runs were harsh on small models: many cells ended after one call with
parts unanswered. `nudge_bench.sh` repeats task-a, then continues the **same
session** with one generic nudge ("list which of (a),(b),(c) are still
unanswered, complete only those"). Combined-session scoring, 3 attempts:

| model | one-shot task-a | + one nudge |
|---|---|---|
| gemma4:12b (11.9B, Q4_K_M) | 0/3 | 1/3 |
| qwen3:4b (4.0B, Q4_K_M) | 0/3 | 0/3 |

A patient user lifts the 12B sometimes and the 4B never; below ~27B dense
(Q4_K_M), completion of this three-part task remains unreliable one-shot.
Separately, an interactive LM Studio run (tag `lmstudio-interactive`: LM Studio
0.4.20, server 0.1.0, Qwen3.6-35B-A3B Q4_K_M, Prompt B, multi-turn) completed
all three parts in 7 calls, including self-recovery from the protected-name
trap — transcript analysis in
[`../examples/latex-decomposition-test.md`](../examples/latex-decomposition-test.md).

## Method & hygiene notes

* One opencode run per cell (`--auto --format json`), fresh server per cell,
  `MACAULAY2_MCP_JOURNAL=off`, session state never crosses cells.
* `results/raw/*.jsonl` keep every event; `collect.py` extracts the **verbatim
  M2 code strings and final answer per cell into `results/bench.csv`** —
  every claim above is re-checkable from that file.
* Runs have full tool approval; one wrote scratch `part_*.m2` files via the write
  tool (cleaned up).
* `run_bench.sh` takes `MODELS`/`TASKS`/`ATTEMPTS` from env.
