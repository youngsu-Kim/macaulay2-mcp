# Example prompts and genuine outputs

> Also see [latex-decomposition-test.md](latex-decomposition-test.md) — a self-serve benchmark of LaTeX-style chat prompts (with ground truth and grading rubric).

Every transcript below was captured from a live `macaulay2` MCP session
(server 0.1.0, Macaulay2 1.26.06). The prompt lines are phrased as you would
type them to Claude Code / opencode; the code blocks show what the server
returned from `m2_evaluate` (M2's own rendering, input echoes included).

Section 1 is core Macaulay2 through the tools; sections 2–5 are what only
*this server* does: how long runs, stops, big batches, and failures actually
present themselves to you and your assistant.

---

## 1. Your first computation: Groebner basis, resolution, Betti table

> Create `R = QQ[x,y,z]` and `I = ideal(x^3 - y, x^4 - z)`. Compute the
> Groebner basis and a graded free resolution; show the Betti table.

```
m2_evaluate("R = QQ[x,y,z]
I = ideal(x^3 - y, x^4 - z)
print generators (gb I)
G = res I
betti G")
```

```
i2 : R = QQ[x,y,z]

o2 = R

o2 : PolynomialRing

i3 : I = ideal(x^3 - y, x^4 - z)

             3       4
o3 = ideal (x  - y, x  - z)

o3 : Ideal of R

i4 : print generators (gb I)
| xy-z x2z-y2 y3-xz2 x3-y |

i5 : G = res I

      1      4      4      1
o5 = R  <-- R  <-- R  <-- R

     0      1      2      3

o5 : Complex

i6 : betti G

            0 1 2 3
o6 = total: 1 4 4 1
         0: 1 . . .
         1: . 1 . .
         2: . 3 4 1

o6 : BettiTally
```

Five statements, one call, genuine M2 output. (The `gb`-is-an-object idiom
and friends are built into the server's instructions, so your assistant
already speaks them.) A longer single-call transcript of this exact task:
[groebner-demo.md](groebner-demo.md).

## 2. The safety net on long runs

> Compute something heavy (here: an infinite loop) with a 3-second limit.

```
m2_evaluate("while true do()", timeout_s=3)
```

```
TIMED OUT: the Macaulay2 computation did not finish within 3 seconds.
This limit is enforced by the macaulay2-mcp server (its author-set default,
currently 3600s maximum) as a safety guard against runaway or infinite
computations hanging the shared M2 session — it is NOT an error reported by
Macaulay2.
The session was restarted, so objects defined earlier (rings, ideals, ...)
no longer exist.
If this computation is legitimately expected to take longer, retry with a
larger timeout, e.g. m2_evaluate(<code>, timeout_s=600), and include all
setup (ring/ideal definitions) in the same code block.
```

Right after the timeout the session is healthy again (`1 + 1` → `2`), but
empty by design — retries must be self-contained.

## 3. Stop a runaway without losing anything

> That computation is taking too long — cancel it.

The assistant calls `m2_interrupt` while the runaway evaluation is still in
flight:

```
m2_evaluate("while true do()", timeout_s=60)      <- still running...
m2_interrupt()
```

`m2_interrupt` returns:

```
Interrupt sent (SIGINT). If the computation is interruptible, the running
m2_evaluate will return shortly with an 'error: interrupted' note and the
session keeps all earlier definitions.
```

and the waiting call completes gracefully:

```
i6 : while true do()
stdio:6:6:(3):[1]: error: interrupted

NOTE(macaulay2-mcp): the computation was stopped on request (m2_interrupt). Everything
defined by statements that completed before the interrupted one is still
available; the session is ready for new input.
```

Crucially, **nothing was lost** — `keepMe = 99` defined before the runaway
loop still evaluates to `99`. So: a *timeout* (§2) restarts the kernel and
clears state; an *interrupt* stops only the current statement and keeps it.

## 4. A family of computations — in a loop, or truly in parallel

> For the family `I_k = (x^(k+2) - y, x^(k+3) - z)` in `QQ[x,y,z]`, tabulate
> the reduced Groebner basis sizes and the dimensions of `R/I_k` for
> `k = 1..6`.

**In one session**, a loop suffices:

```
for k from 1 to 6 list (J := ideal(x^(k+2) - y, x^(k+3) - z); (k, #flatten entries generators gb J, dim (R/J)))
```

```
o = {(1, 4, 1), (2, 5, 1), (3, 6, 1), (4, 7, 1), (5, 8, 1), (6, 9, 1)}
```

**For heavy families**, ask for it "as independent batch jobs" instead: each
`m2_run_script` call spawns its own M2 process, so three subagents slicing
`k = 1..6` is genuine 3-way parallelism. Genuine run — each subagent's slice
is a small self-contained script like:

```
-- job slice: k = 1, 2 of the family
R = QQ[x,y,z]
for k from 1 to 2 list (
    J := ideal(x^(k+2) - y, x^(k+3) - z);
    print ("k=" | toString k | " gbGens=" | toString (#flatten entries generators gb J) | " dim=" | toString (dim (R/J)))
)
```

and the orchestrator collects:

```
SLICE 1 RESULT:  k=1 gbGens=4 dim=1   k=2 gbGens=5 dim=1
SLICE 2 RESULT:  k=3 gbGens=6 dim=1   k=4 gbGens=7 dim=1
SLICE 3 RESULT:  k=5 gbGens=8 dim=1   k=6 gbGens=9 dim=1
```

— matching the loop answer exactly. Your assistant makes this happen with the
client's own fan-out (parallel tool calls or subagents); the server is
concurrency-safe by design: session calls serialize on one kernel, batch jobs
each get their own process.

## 5. When something goes wrong

Real M2 errors arrive **verbatim**, not swallowed:

> Compute the Hilbert polynomial of the (non-homogeneous!) ideal from §1.

```
i14 : hilbertPolynomial coker gens I
stdio:14:17:(3):[1]: error: hilbertPolynomial: expected a homogeneous module
```

Your assistant sees exactly this message and can adjust (`x^3 - y` mixes
degrees, so the Hilbert polynomial doesn't apply — a homogeneous example
would). And when a multi-statement run hits an error mid-way, M2 being a
REPL means later statements still ran; the server then appends the options
instead of choosing for you:

```
i3 : noSuchFn(1)
stdio:3:8:(3):[1]: error: no method for adjacent objects: ...

NOTE(macaulay2-mcp): M2 reports an error above, but as a REPL, it did NOT
halt — inputs after the failing line already ran (possibly on broken
assumptions), and M2 has no rollback ... Before retrying, ask the user how
to proceed:
  (1) CONTINUE — resend only the corrected failing statement ...
  (2) RESTART — m2_session_reset, then rerun a corrected, self-contained
      block. This is irreversible: ALL current session definitions are lost.
  (3) INSPECT — evaluate the affected names first ...
```

So the recovery decision stays with **you**; your assistant relays the
options. If you'd rather nothing run after the first error, ask for the code
to be sent with `stop_on_error=True` — the run then halts at the failing
statement and later lines never execute.
