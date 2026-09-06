# The official Macaulay2 tutorial, driven over MCP

The examples below are taken verbatim (or near-verbatim) from Macaulay2's own
teaching material — *"a first Macaulay2 session"* (Macaulay2Doc) and
*BeginningMacaulay2* (Eisenbud–Stillman), the pages linked from
[macaulay2.com/GettingStarted](https://macaulay2.com/GettingStarted/) —
executed through `m2_evaluate` on **Macaulay2 1.26.06** via this MCP server.
Outputs are genuine captures, lightly trimmed.

**Session semantics, learned the hard way:** the docs project builds each
tutorial example in an *isolated* M2 session. In our persistent session,
names persist, so replaying sections back-to-back can contaminate them
(`a`, `b`, … may already hold ring elements). The official tutorial's own
prescription applies: `name = symbol name` to clear a name — or simply ask
your assistant to start with `m2_session_reset` between unrelated topics.

Running this battery is also what caught two bugs in this server, now fixed:
the completion marker used to pollute M2's `oo`/`ooo` history (F13) and the
`stop_on_error` splitter used to break the tutorial's Collatz example at its
`Collatz = n ->` line break (F14). Everything below reflects the fixed code.

---

## 1. Arithmetic and the output history (`oo`)

```
m2_evaluate("2+2\n107*431\n25!\nbinomial(5,4)\nfactor 32004")
```
```
o2 = 4
o3 = 46117
o4 = 15511210043330985984000000
o5 = 5
      2 2
o6 = 2 3 7*127        ← 32004 = 2² · 3² · 7 · 127 (superscripts print above)
```

The tutorial's semicolon lesson — and the reason F13 mattered:

```
m2_evaluate("4*5;")   →  i8 : 4*5;          (result suppressed)
m2_evaluate("oo")     →  o10 = 20           (correct! pre-fix returned 1)
```

Loops as one-liners:

```
j=1; scan(10, i -> j = 2*j); j     →   o = 1024
```

## 2. Fields, rings, ideals

```
k = toField (QQ[i]/(i^2+1))
1/i                                   →   o = -i          (i² = −1)
```
```
kk=ZZ/101
S=kk[a,b,c,d,e]
(3*a^2+1)^5
```
```
         10    8      6      4      2
o21 = 41a   + a  - 33a  - 11a  + 15a  + 1
```

```
I=ideal(a^3-b^3, a+b+c+d+e)
R=S/I
dim R                                 →   o = 3
```

## 3. Matrices and modules

```
Mm = matrix{{a,b,c},{b,c,d},{c,d,e}}  →   | -b-c-d-e b c |   (over the quotient R!)
determinant Mm ; trace Mm             →   o29 = - b - d
kernel matrix"a,b,0;0,a,b"            →   image of a 3×3 matrix (compact string syntax)
```

## 4. Gröbner bases and primary decomposition

```
R2 = ZZ/32003[x,y,z,w]
I2 = ideal(x^2*y, x*y^2+x^3)
print generators gb I2                →   | x2y  x3+xy2  xy3 |
```

The tutorial's intersection-then-decompose example, matching its prose
("the first two are the same…, the third differs"):

```
J3 = intersect(ideal"x2,y3", ideal"y2,z3", (ideal"x,y,z")^4)
print primaryDecomposition J3
```
```
{ideal (x2, y3), ideal (y2, z3), ideal (z, x, y4)}
```

## 5. The (1,3,4) rational quartic — the curve from our README

```
R3 = ZZ/101[a..d]
I3 = monomialCurveIdeal(R3,{1,3,4})
(dim I3, codim I3, degree I3)         →   (2, 2, 4)
hilbertPolynomial(R3/I3)              →   - 3*P0 + 4*P1    (= 4i + 1: degree 4, genus 0)
M3 = R3^1/I3
print betti res M3
```
```
       0 1 2 3
total: 1 4 4 1
    0: 1 . . .
    1: . 1 . .
    2: . 3 4 1
```

The tutorial's reading rule ("the number in column j, row d means degree
j+d"): the last free module has `1` generator at column 3, row 2 → degree
**5** — exactly as its text states. Note `monomialCurveIdeal` produces the
*saturated* prime; the README's `(x^3−y, x^4−z)` is the non-saturated
subideal that happens to share this Betti table.

## 6. Division with remainder (trace powers)

```
R4 = ZZ/101[a..i]
M4 = genericMatrix(R4,a,3,3)
I4 = ideal M4^3                        ← entries of M³ generate the ideal
Tr = trace M4                          →   a + e + i
for p from 1 to 8 list ((Tr^p % I4) == 0)
```
```
{false, false, false, false, false, false, true, true}
```

Confirming the tutorial's claim to the letter: *"the 6-th power of the trace
is NOT in the ideal … but the 7-th power is."* Then the coefficients:
`Tr^7 // (gens I4)` exhibits the explicit combination.

## 7. Elimination: projecting the twisted cubic

```
x = symbol x                           ← the official symbol-reset pattern
R5 = ZZ/101[x_0..x_3]
Mt = map(R5^2, 3, (i,j) -> x_(i+j))    ← catalecticant/Hankel matrix
It = minors(2, Mt)                     ← twisted cubic ideal
J5 = kernel map(R5/It, ZZ/101[u,v,w], gens ideal(x_0+x_3, x_1, x_2))
print saturate ideal singularLocus J5  ← "doesn't look reduced — because unsaturated"
```

## 8. Ext, Tor, and sheaf cohomology (the homepage claims)

Serre's formula for two planes meeting two planes in 4-space — the case
where "length of the intersection scheme is NOT the right answer":

```
S6 = ZZ/101[a,b,c,d]
IX = intersect(ideal(a,b), ideal(c,d))   ← union of two 2-planes
IY = ideal(a-c, b-d)                     ← a 2-plane
degree ((S6^1/IX) ** (S6^1/IY))          →   3
for j from 0 to 4 list degree Tor_j(S6^1/IX, S6^1/IY)
                                         →   {3, 1, 0, 0, 0}
```

(Intersection multiplicity = alternating sum = 3 − 1 = **2**.) Plus:

```
print Ext^1(IX, S6^1/IY)   →  subquotient (matrices)   ← Hom/Ext computable
print HH^1 (sheaf (S6^{-2}**(S6^1/IX)))
                           →  (ZZ/101)^2               ← sheaf cohomology,
                                                          the homepage promise
```

## 9. Loops, functions, and stop_on_error — the Collatz example

The tutorial's multi-line function definition — the case that broke the old
splitter (F14), now a pinned test:

```
Collatz = n ->
    while n != 1 list if n%2 == 0 then n=n//2 else n=3*n+1
length Collatz 27                       →   111
```

Issued with `stop_on_error=True`, the `->` line break is correctly kept as
one chunk; the `for n from 1 to 30 list length Collatz n` and `tally`
examples from the tutorial run unchanged. (The `randomGraph` section is
deliberately *not* output-pinned: results depend on the date-seeded RNG.)

---

### What this battery proves about the MCP layer

1. Everything the official pages advertise works through plain prompts to
   your assistant — no Emacs, no terminal.
2. Persistent state is real (rounds build on each other *within* a topic),
   and its one hazard (name reuse across topics) has the official one-liner
   fix, which the server's instructions now teach.
3. The safety machinery (void marker, `oo` history, splitter, error menus,
   gate) was validated against first-party material that the M2 project
   itself CI-checks — a ground-truth source stronger than any example we
   could invent.
