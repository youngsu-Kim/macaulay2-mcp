"""Offset-preserving scanner for Macaulay2 source text.

Shared by ``ends_unbalanced``, ``split_logical_inputs`` and the gatekeeper so
all three reason about *code* rather than text that merely appears inside
string literals or ``-- comments``.

``mask()`` returns text of the SAME LENGTH as the input:

* ``-- ...`` comment bodies (including the ``--``) become spaces;
* string-literal INTERIORS (and backslash escapes) become spaces;
* the string delimiters themselves are kept (so a lone ``"abc"`` line still
  reads as content).

It also reports whether the text ends inside an unterminated string.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Masked:
    text: str
    ends_in_string: bool


def mask(code: str) -> Masked:
    out = list(code)
    i, n = 0, len(code)
    in_str = False
    while i < n:
        c = code[i]
        if in_str:
            if c == "\\":
                out[i] = " "
                if i + 1 < n and code[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if c == '"':
                in_str = False
                i += 1
                continue
            if c != "\n":
                out[i] = " "
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == "-" and i + 1 < n and code[i + 1] == "-":
            j = i
            while j < n and code[j] != "\n":
                out[j] = " "
                j += 1
            i = j
            continue
        i += 1
    return Masked("".join(out), in_str)
