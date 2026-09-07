# Example prompts and genuine outputs

> Also see [latex-decomposition-test.md](latex-decomposition-test.md) — a self-serve benchmark of LaTeX-style chat prompts (with ground truth and grading rubric).

Every transcript below was captured from a live `macaulay2` MCP session
(server 0.1.0, Macaulay2 1.26.06). The prompt lines are phrased as you would
type them to Claude Code / opencode; the code blocks show what the server
returned from `m2_evaluate` (M2's own rendering, input echoes included).

Tip that shows up in all of these: **end statements with newlines, not
semicolons** — M2 suppresses the printed result of any `statement;` (see §7).

---

## 1. Groebner basis, resolution, Betti table

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

Note the M2-1.26 idiom: `gb I` returns a `GroebnerBasis` object, so the basis
polynomials are seen via `print generators (gb I)`. (This guidance is built
into the server's instructions, so your assistant should already know it.)

## 2. Dimensions — quick geometric sanity checks

> What are the dimensions of `R` and of `R/I`?

```
i15 : dim R

o15 = 3

i16 : dim (R/I)

o16 = 1
```

`R/I` is the monomial (3,4)-curve: dimension 1. Keep the parentheses —
`dim R/I` parses differently in M2.

## 3. Hilbert polynomial of the twisted cubic (via `m2_help` first)

> Look up the documentation for `hilbertPolynomial` and compute it for the
> twisted cubic `(x*z - y^2, y*w - z^2, x*w - y*z)`.

```
i16 : S = QQ[x,y,z,w]

i17 : J = ideal(x*z - y^2, y*w - z^2, x*w - y*z)

i18 : hilbertPolynomial J

o18 = - 2*P  + 3*P
           0      1

o18 : ProjectiveHilbertPolynomial
```

`3P₁ − 2P₀` is M2's binomial-basis notation for `3T + 1` — degree 3, genus 0.

Gotcha: `help "HilbertPolynomial"` (CamelCase) is a dead doc pointer in 1.26
— it returns an empty stub. Use the function's real name, `hilbertPolynomial`.
The server surfaces the stub verbatim, so a quick `m2_help` retry finds the
real page.

## 4. Primary decomposition

> Compute the primary decomposition of `ideal(x^2, x*y)`.

```
i24 : K = ideal(x^2, x*y)

i25 : print primaryDecomposition K
{ideal x, ideal (y, x )}
                     2
```

i.e. `(x², xy) = (x) ∩ (x, y)²`. The `PrimaryDecomposition` package is
preloaded in 1.26, so no loading needed (`m2_list_packages` shows what is
available in the session; `m2_load_package` reports “already loaded” no-ops).

## 5. Boij–Söderberg decomposition of a Betti diagram

> Load the `BoijSoederberg` package and decompose the Betti diagram of
> `res I` into pure diagrams (`decomposeBetti`).

```
i9 : R = QQ[x,y,z]

i10 : I = ideal(x^3 - y, x^4 - z)

i11 : decomposeBetti betti res I

        1 /       0  1  2 3\     1 /       0  1  2 3\    2 /       0 1 2\
o11 = (--)|total: 3 10 15 8| + (--)|total: 1 10 15 6| + (-)|total: 1 4 3|
       10 |    0: 3  .  . .|    30 |    0: 1  .  . .|    3 |    0: 1 . .|
          |    1: . 10  . .|       |    1: .  .  . .|      |    1: . . .|
          \    2: .  . 15 8/       \    2: . 10 15 6/      \    2: . 4 3/

o11 : Expression of class Sum
```

A positive rational combination of pure Betti diagrams — the Boij–Söderberg
theorem made visible.

## 6. Real M2 errors are surfaced, not swallowed

> Compute the Hilbert polynomial of the (non-homogeneous!) ideal from §1.

```
i14 : hilbertPolynomial coker gens I
stdio:14:17:(3):[1]: error: hilbertPolynomial: expected a homogeneous module
```

The Groebner-basis ideal of §1 is *not* homogeneous in the standard grading
(`x^3 - y` mixes degrees 3 and 1), so the Hilbert polynomial doesn't apply.
The assistant sees exactly this message and can adjust (e.g. §3's homogeneous
example, or use `betti` directly).

## 7. The trailing-semicolon trap (why results sometimes "vanish")

```
i26 : betti G;

i27 : print "previous line produced NO output: M2 suppresses results of statements ending with a semicolon"
previous line produced NO output: M2 suppresses results of statements ending with a semicolon
```

M2 treats a trailing `;` as "don't print this result". This tripped the
small local models in our Docker E2E until the rule was written into the
server's instructions. If a result seems missing, ask for it without `;` or
with an explicit `print`.

## 8. Timeouts are the server's guard, not M2's error

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

Right after the timeout, the session is healthy again (`1 + 1` → `2`), but
empty by design — retries must be self-contained.

## 9. Stopping a running computation (m2_interrupt)

> That computation is taking too long — cancel it.

The assistant calls `m2_interrupt` *while the runaway `m2_evaluate` is still
in flight* (two concurrent requests on one connection; the interrupt is
lock-free by design):

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

and the waiting `m2_evaluate` call completes gracefully:

```
i6 : while true do()
stdio:6:6:(3):[1]: error: interrupted

NOTE: the computation was stopped on request (m2_interrupt). Everything
defined by statements that completed before the interrupted one is still
available; the session is ready for new input.
```

Crucially, **nothing was lost** — `keepMe = 99` defined before the runaway
loop still evaluates to `99` in the same session. Contrast with §8: a
*timeout* kills and restarts the kernel (state gone); an *interrupt* aborts
only the current statement (state kept).

## 10. A family of ideals indexed by k (loops)

> For the family `I_k = (x^(k+2) - y, x^(k+3) - z)` in `QQ[x,y,z]`, loop over
> `k = 1..6` and tabulate the reduced Groebner basis sizes and the dimensions
> of `R/I_k`.

**Style A — collect invariants** (`for ... list` returns a list; `:=` scopes
`J` locally per iteration):

```
for k from 1 to 6 list (J := ideal(x^(k+2) - y, x^(k+3) - z); (k, #flatten entries generators gb J, dim (R/J)))
```

```
o = {(1, 4, 1), (2, 5, 1), (3, 6, 1), (4, 7, 1), (5, 8, 1), (6, 9, 1)}
```

(The Groebner basis gains one generator per step; the quotient stays a curve.
This exact output is pinned in the golden regression dataset.)

**Style B — display per-k tables** (`scan` + explicit `print`):

```
scan({1, 2}, k -> (J := ideal(x^(k+2) - y, x^(k+3) - z); print k; print betti res J))
```

```
1
       0 1 2 3
total: 1 4 4 1
    0: 1 . . .
    1: . 1 . .
    2: . 3 4 1
2
       0 1 2 3
total: 1 5 6 2
    0: 1 . . .
    1: . 1 . .
    2: . . . .
    3: . 4 6 2
```

**Beginner traps this exercises** (all verified on M2 1.26.06, and encoded in
the server's instructions so your assistant avoids them):

* `I_k = ...` defines ONE symbol literally named `I_k` — underscore is a name
  character, not indexing. Make `k` a function parameter:
  `I = k -> ideal(x^(k+2) - y, x^(k+3) - z)`, then call `I 3` or `I(k)`.
* Inside a loop body, `J := ...` scopes locally per iteration; a bare `J = ...`
  would overwrite a global.
* `dim (R/J)` needs the parentheses: `dim R/J` parses differently.
* `print a | b` is `(print a) | b` — parenthesize concatenations:
  `print (a | b)`.

## 11. Parallel batch jobs, fanned out across subagents

> Same family, k = 1..6, but split the work across three subagents, each
> running its own slice as an isolated `m2_run_script` job.

`m2_evaluate` uses one shared kernel (state cooperation, serialized by
design). For independent heavy work, each `m2_run_script` call spawns **its
own M2 process** — so N concurrent jobs = genuine N-way parallelism.

Genuine run: three parallel subagents, each given one slice file, e.g.
`/tmp/m2-demo/slice1.m2`:

```
-- job slice: k = 1, 2 of the family I_k = (x^(k+2) - y, x^(k+3) - z) in QQ[x,y,z]
R = QQ[x,y,z]
for k from 1 to 2 list (
    J := ideal(x^(k+2) - y, x^(k+3) - z);
    print ("k=" | toString k | " gbGens=" | toString (#flatten entries generators gb J) | " dim=" | toString (dim (R/J)))
)
```

Each subagent simply runs `m2_run_script(path=...)` on its file; the
orchestrator collects the three results (one M2 process per job, run
concurrently — transcripts below from a real three-subagent fan-out; the
trailing batch prompt is stripped in the current build):

```
SLICE 1 RESULT:  k=1 gbGens=4 dim=1   k=2 gbGens=5 dim=1
SLICE 2 RESULT:  k=3 gbGens=6 dim=1   k=4 gbGens=7 dim=1
SLICE 3 RESULT:  k=5 gbGens=8 dim=1   k=6 gbGens=9 dim=1
```

— matching §10's single-loop answer exactly.

Notes:

* Slices are self-contained (batch jobs share no state) — include all setup
  in every script.
* The host decides the fan-out: parallel tool calls in one turn, or
  subagents (opencode `task` / Claude Code subagents). Both hammer the same
  concurrency-safe server.
* Tests pin the two halves of this story: concurrent `m2_evaluate` requests
  return correctly paired results (serialization safety), and concurrent
  `m2_run_script` jobs all return correct output (parallel existence). No
  timing claims anywhere.
* Footnote: M2 also has an in-kernel `parallelApply`; this project steers
  beginners toward job-level parallelism, and first-class job handles
  (`m2_submit_job` / status / wait / cancel over a kernel pool) are planned
  for a later version.

## 12. Error handling: cascades, halts, and choosing the recovery

> Define `sBefore = 7`, compute something that fails, then `sAfter`.

Default (REPL) semantics — M2 **keeps running** after the error, and the
server appends the options menu instead of deciding for you (genuine
transcript, server 0.1.0):

```
i2 : sBefore = 7
o2 = 7
i3 : noSuchFn(1)
stdio:3:8:(3):[1]: error: no method for adjacent objects: ...
i4 : sAfter = sBefore + 1
o4 = 8

NOTE(macaulay2-mcp): M2 reports an error above, but as a REPL, it did NOT
halt — inputs after the failing line already ran (possibly on broken
assumptions), and M2 has no rollback ... Before retrying, ask the user how
to proceed:
  (1) CONTINUE — resend only the corrected failing statement ...
  (2) RESTART — m2_session_reset, then rerun a corrected, self-contained
      block. This is irreversible: ALL current session definitions are lost.
  (3) INSPECT — evaluate the affected names first ...
```

The same block with `stop_on_error=True` — everything after the error is
never executed (note `p2` stays undefined afterwards):

```
m2_evaluate("p1 = 1\nnoSuchFn(9)\np2 = p1 + 1\np3 = p1 + 2",
            stop_on_error=True)
```

```
i8 : p1 = 1
o8 = 1
i10 : noSuchFn(9)
stdio:10:8:(3):[1]: error: no method for adjacent objects: ...

NOTE(macaulay2-mcp): the run halted at the failing input (stop_on_error):
2 later input(s) were NOT executed. M2 has no rollback, so the failing
line's earlier statements took effect ... Before retrying, ask the user ...
```

```
m2_evaluate("p2")  →  o12 = p2 : Symbol     ← never assigned
```

Semantics worth knowing, all pinned by golden tests:

* No rollback even *within* a line: `x = 2; bogusFn(x)` leaves `x = 2`
  defined after erroring (golden `partial_input_effect`).
* `stop_on_error` requires self-contained lines (splitting happens at
  top-level newlines; don't break a line after a binary operator).
* `m2_run_script` is the opposite by design: batch mode with M2's `--stop`
  halts at the first error.
