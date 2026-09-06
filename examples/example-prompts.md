# Example prompts and genuine outputs

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
