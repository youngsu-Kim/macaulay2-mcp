# Test your assistant with LaTeX math (the chat-box workflow)

Most people type mathematics into a chat box the way they write it on paper —
`$I = (x^3 - y, x^4 - z)$ in $\mathbb{Q}[x,y,z]$` — not as
`ideal(x^3 - y, x^4 - z)`. This page is a **do-it-yourself benchmark** of that
workflow against a live `macaulay2-mcp` server, plus the verified result of
running it here first.

What the test separates three distinct skills:

1. **Translation** — LaTeX notation → valid M2 syntax.
2. **Decomposition** — a multi-part request → one goal per tool call.
3. **Verification** — reading tool output honestly (no answering from memory
   when a display came back suppressed or empty).

## The prompts (copy-paste into your MCP client)

### Prompt A — raw

```text
Let $S = \mathbb{Q}[x,y,z]$ and $I = (x^3 - y, x^4 - z)$, a monomial space curve.
(a) Compute the reduced Groebner basis of $I$ and list its elements.
(b) Compute a minimal free resolution of $S/I$ and display its Betti table.
(c) State $\dim(S/I)$.
Do not answer anything you have not seen in a tool output.
```

### Prompt B — with decomposition scaffolding

Same text, plus this final paragraph:

```text
Work on one part at a time: issue a separate m2_evaluate per part, check that
the tool output actually printed the result before moving to the next, and if
a call printed nothing, fix the command (M2 suppresses a result ending in ";")
and rerun rather than answering from memory.
```

## Grading rubric (the ground truth is already known — from real M2 runs)

| Check | Pass condition |
|---|---|
| Translation | issues `R = QQ[x,y,z]` and `ideal(x^3 - y, x^4 - z)` |
| (a) | tool output shows `xy-z x2z-y2 y3-xz2 x3-y` (superscripts render as plain digits — faithful) |
| (b) | a displayed table with `total: 1 4 4 1` |
| (c) | `dim ... = 1` appears in output |
| Decomposition | all three parts answered, none dropped |
| Honesty | no claimed number absent from any tool output |

## Verified run (2026-09-07) — model under test: Qwen 3.8 Flash Next

Two clean-context subagents, same server (Macaulay2 1.26.06), session reset
between runs. **n = 1 each: an anecdote, not a statistic.**

| Rubric row | Prompt A | Prompt B |
|---|---|---|
| Translation | ✅ | ✅ |
| (a) basis | ✅ | ✅ |
| (b) Betti | ✅ | ✅ |
| (c) dim = 1 | ✅ | ✅ |
| All three parts | ✅ | ✅ |
| Nothing from memory | ✅ | ✅ |
| Efficiency | 8 calls, ~10 M2 method-name errors, all recovered | 5 calls + 1 `m2_help`, 2 errors, recovered |

### Prompt A — key excerpts

Setup + basis, first call:

```text
i5 : print (generators G)
| xy-z x2z-y2 y3-xz2 x3-y |
```

Not content to assert "reduced", A *proved it from outputs*:
leading coefficients monic (`{true,true,true,true}`), leading terms mutually
non-dividing (all-`false` matrix), tails standard mod the initial ideal
(`{true,true,true,true}`). It also cross-checked the Betti table two ways
(`res I` and `res coker gens I` — identical) and reported `deg I = 4` only
after M2 printed it.

Errors it absorbed (none of these exist in 1.26, all guessed):
`G#isReduced`, `elements G`, `selectTerms`, `ranks F`, `R^1 // I`,
`reducedGB`… every one recovered from the error menu without a session reset.

### Prompt B — key excerpts

Same basis display (`xy-z x2z-y2 y3-xz2 x3-y`), then, when the two "give me a
reduced basis" spellings failed (`gb(I, Reduce => true)`, `reducedGB I`), B
resolved the question by **consulting the documentation tool** —
`m2_help "gb"` — which states `generators (gb I)` yields the auto-reduced
basis. The scaffolded rule "check the output before moving on" showed up as:
explicit `print` everywhere (zero suppressed displays) and one evaluate per
part.

```text
i14 : print betti res I
       0 1 2 3
total: 1 4 4 1
    0: 1 . . .
    1: . 1 . .
    2: . 3 4 1

i16 : print ("dim(S/I) = " | toString (dim I))
dim(S/I) = 1
```

### The one blemish both shared (and what it teaches)

Transcribing the table: perfect, both. Converting it to doubly-indexed
$\beta_{i,j}$ prose: both mislabeled one entry (row/column convention is
subtle). The tool output was never wrong — the recoloring into notation is
where care is needed. Lesson for readers: **keep the displayed table as the
record**, and re-check any hand-translated indices.

## How the field did on this task (bench grid, 2026-09-06, 48 cells)

Full method and caveats in [`../bench/README.md`](../bench/README.md). Same two
prompts (A raw, B scaffolded), three attempts each, all models 4-bit `Q4_K_M`
via Ollama on one Apple Silicon host:

| model | raw A | scaffolded B |
|---|---|---|
| dense 4B–12B (qwen3:4b, qwen3.5:4b, qwen3:14b, gemma4:e2b/e4b/12b; Q4_K_M) | 0/18 | 1/18 |
| **dense 27B Q4_K_M (qwen3.6:27b, qwen3.8:27b)** | **3/6 + 1/6** | **1/6 + 3/6** |
| frontier hosted, multi-turn chat (qwen3.8 Flash Next) | 1/1 | 1/1 |
| LM Studio interactive, Qwen3.6-35B-A3B Q4_K_M (`lmstudio-interactive`) | - | 1/1 |

Three facts from the 48 transcripts:

* 48/48 cells translated the LaTeX notation to valid M2 syntax on the first
  call; no failure was a mistranslation.
* No cell contained a number absent from tool outputs. The recurring local
  failure is the run ending after one call, answering only part (a).
* The step between dense 11.9B (0/6) and dense 27B (4/6 each, Q4_K_M) is where
  this task starts completing one-shot. An earlier published "0/25" overstated
  the failure: the grader had missed M2's bare-value printing (`dim I` outputs
  `o7 : 1`, not `= 1`); the bench grid re-scored everything from raw logs.

## Case study: the Hilbert-series trap

A chat agent (LM Studio, Qwen3.6-35B-A3B, 4-bit), given this very problem
**with no tool access**, produced the following chain: it proved `S/I ≅ Q[t]` (correct),
declared the Hilbert series `1/(1-t)` (wrong), compared against the Betti table
(consequently nonsense), and concluded that `res I` "computes the resolution of
nothing". The fatal step is invisible-but-simple: **I = (x^3-y, x^4-z) is not a
homogeneous ideal** (`x^3 - y` mixes degrees), so `S/I` has no standard-graded
Hilbert series at all — every identity built on it is vacuous. The ring
isomorphism `S/I ≅ Q[t]` is true but *not grading-preserving*: `y ↦ t^3` gives
`t` fractional degree. M2's `total: 1 4 4 1` is simply the minimal free
resolution of the ideal `I` (verified two independent ways in the transcripts
above).

This was a 35B MoE model (~3B active parameters), single-pass chat, no tools.
The passing runs above were multi-turn and tool-grounded. The server's
instructions now tell assistants
to (1) suspect hidden assumptions like homogeneity before condemning the engine,
and (2) consult `m2_help` offline, or the Macaulay2 documentation online when
the client can fetch web pages, instead of re-deriving invariants from memory.
A web-search/fetch MCP alongside this server would let the assistant consult
the online documentation in this situation; we have not measured that
configuration.

## The same model, two worlds

> Test tag: `lmstudio-interactive` - LM Studio 0.4.20, server 0.1.0
> (pre-0.1.1 instructions), model Qwen3.6-35B-A3B 4-bit, Prompt B,
> interactive multi-turn chat, 2026-09-07.

The no-tools spiral above (LM Studio, **Qwen3.6-35B-A3B**, 4-bit) and this
grounded run are **the same model**, same machine, minutes apart:

The same model was then given Prompt B (scaffolded) with this MCP server
connected. Seven `m2_evaluate` calls, all three parts completed:

1. `gens gb I; print G` -> basis displayed.
2. `coker matrix{...}` + `resolution M` -> error, moved on.
3. `resolution (R/I)` -> error (quotient ring), moved on.
4. `res = resolution I` -> error (**`res` is protected — the exact trap the
   server instructions now warn about**), moved on.
5. `print resolution I` -> complex displayed.
6. `print betti (resolution I)` -> `total: 1 4 4 1` displayed.
7. `print dim (R/I)` -> `1` displayed.

Final answer reproduced the basis, the table, and the dimension, each backed by
quoted output. One residue: the prose claimed the basis was w.r.t.
"lexicographic order" — no tool output ever showed the monomial order (M2's
default is graded reverse lexicographic). Same failure family as the β-index
mislabels: the transcribed numbers were honest; the *label from memory* was
not.

| run | tools | outcome |
|---|---|---|
| free-form chat, no tools | none | invented a Hilbert-series argument, concluded `res I` computes nothing |
| Prompt B + this server | m2_evaluate x7 | all three parts grounded in displayed output; recovered from 3 wrong-command errors unaided |

The model did not change. The scaffolding around it did.

## Try it yourself

1. Connect any MCP client to `uvx macaulay2-mcp` (see the README's 30-second
   setup).
2. Paste Prompt A. Grade against the rubric — the expected values are listed
   above; compare digit for digit.
3. Paste Prompt B in a fresh chat. Compare.
4. If B outperforms A, the model needs decomposition guidance. The server's
   own instructions may adopt this wording in a later version.
