# Reading the journal

← back to the [README](../README.md)

As a default, the MCP server keeps the history (journal) in a file — an
append-only log of every exchange: one JSON Lines file per server run, one
JSON object per line. It lands in `.m2-mcp/` in the working directory of the
app that started the server; relocate it with `MACAULAY2_MCP_JOURNAL=<dir>`
or turn it off with `=off` (the LM Studio entry in the README's 30-second
setup, for instance, pins it to `~/.local/share/macaulay2-mcp/journals/`).

Why it exists: when an AI assistant computes on your behalf, "what exactly
ran, and what came back?" deserves an answer that outlives the chat
scrollback. Each record carries the exact code, M2's full output (fields cap
at 1 MiB), outcome flags (timeout / error / interrupted / stopped), elapsed
time, the kernel's memory measurements (`rss_bytes`, `peak_rss_bytes`,
`swap_bytes`), and which M2 served it; the first line of every file is a
header with the server version and the identity of the connected client. Gate
refusals are recorded too — the code that was *not* executed. When a long
result is excerpted, the notice's "event seq N" points at the record here
that holds the full text.

Quick looks:

```sh
# one line per call, newest dir last:
jq -c '{seq, event, code}' .m2-mcp/session-*.jsonl

# everything the gate refused:
jq 'select(.event == "os_block") | {t, symbols, code}' .m2-mcp/session-*.jsonl
```

Honest notes: the journal is plain text — nothing redacted, so treat the
folder like your browser history and keep it out of version control
(`.m2-mcp/` in `.gitignore`). The server never reads it back in v0.1
(checkpoint/replay is planned). Deleting files is safe and reversible in the
only sense that matters: the next server run simply starts a new file. The
conversation around these calls lives in your *client's* own storage (e.g.
opencode's session history); the two records agree by timestamp, which is
deliberate.
