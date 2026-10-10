# The OS-access gate

← back to the [README](../README.md)

Why some perfectly normal-looking code is **blocked**: your assistant drives the
Macaulay2 kernel with the same confidence it uses `betti res I` — and in plain
M2, `lines "somefile"` reads any file *your user account* can read. The
operating system grants that permission to you, and M2 inherits it silently:
there is no per-call approval inside Macaulay2. A well-meaning suggestion like
`print lines("~/.ssh/id_rsa")` needs no escalation at all; it simply works —
unless something intervenes.

That intervention — refusing OS-touching functions *before anything executes*
— is a deliberate safeguard **added by this MCP server's author**, not by
Macaulay2 or your client. It exists because the caller at the keyboard is
often a language model, and language models make plausible-but-wrong choices
at machine speed.

One trade-off, stated honestly: the check inspects *words in code position*,
not full program semantics (M2's function-application and higher-order syntax
make "is this word really being *called*?" undecidable without a complete
parser). Side effect: `lines`, `system`, and `quit` are also ordinary English
nouns — so a harmless variable named `lines` (say, counting the 27 lines on a
cubic surface) is refused too. Nothing runs in either case; rename the
variable, or allowlist the symbol via `MACAULAY2_MCP_OS_ALLOW`. The gate
remains friction against accidents, not a sandbox — for real isolation run
the server in a container or VM.
