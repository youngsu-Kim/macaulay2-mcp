# Example: Groebner basis and Betti table

A genuine transcript from the `macaulay2` MCP server (v0.1, M2 1.26.06).
The "user" here is an LLM calling the tools; what it sees is exactly the
`m2_evaluate` output below.

## Tool calls

```
m2_evaluate("R = QQ[x,y,z]\nI = ideal(x^3 - y, x^4 - z)")
m2_evaluate("print generators (gb I)")
m2_evaluate("G = res I\nbetti G")
```

## Output

### 1. Create the ring and ideal

```
i2 : R = QQ[x,y,z]

o2 = R

o2 : PolynomialRing

i3 : I = ideal(x^3 - y, x^4 - z)

             3       4
o3 = ideal (x  - y, x  - z)

o3 : Ideal of R
```

### 2. Groebner basis

```
i5 : print generators (gb I)
| xy-z x2z-y2 y3-xz2 x3-y |
```

(The plain-text printer shows `x^3` as a raised `3`; in the matrix above the
basis is `xy - z, x^2 z - y^2, y^3 - x z^2, x^3 - y`.)

### 3. Resolution and Betti table

```
i7 : G = res I

      1      4      4      1
o7 = R  <-- R  <-- R  <-- R

     0      1      2      3

o7 : Complex

i8 : betti G

            0 1 2 3
o8 = total: 1 4 4 1
         0: 1 . . .
         1: . 1 . .
         2: . 3 4 1

o8 : BettiTally
```

## What a model answer looks like

> The Groebner basis of I = (x^3 - y, x^4 - z) in QQ[x,y,z] is
> {xy - z, x^2z - y^2, y^3 - xz^2, x^3 - y}.
> A graded free resolution has total Betti numbers (1, 4, 4, 1):
> 1 generator in degree 0, 4 syzygies starting in degrees 1 and 2.
