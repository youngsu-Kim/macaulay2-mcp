# Troubleshooting

← back to the [README](../README.md)

| Symptom | Fix |
|---|---|
| `selftest` says *Macaulay2 was not found* | Install M2 (see [Installing Macaulay2](../README.md#installing-macaulay2-details)) or set `M2_BIN`. |
| *Found Macaulay2 1.22.05, but ... only supports 1.26.x* | Upgrade: `brew tap Macaulay2/tap && brew update && brew upgrade macaulay2` or `sudo apt update && sudo apt install macaulay2` (with the M2 PPA added). |
| Server doesn't appear in the client | Restart the client; run `uvx macaulay2-mcp selftest` manually to see errors; check `claude mcp list` (Claude Code) or `opencode mcp list` (opencode). |
| A computation times out | Retry with a larger `timeout_s` (ask your assistant to), or write a script and use `m2_run_script`. To cancel a running computation while keeping session state, have the assistant call `m2_interrupt`. |
| Something about an unbalanced `}` | Your (or the assistant's) code was missing a closing bracket — the error message says so; just fix and resend. |
| A `.m2-mcp/` folder appeared in your project | That is the audit journal (every M2 exchange, one JSONL file per server run). Add it to `.gitignore`, relocate with `MACAULAY2_MCP_JOURNAL=<dir>`, or disable with `MACAULAY2_MCP_JOURNAL=off`. Details: [Reading the journal](journal.md). |
| `BLOCKED: ... gatekeeper refuses '...'` | The assistant tried an M2 function that touches the OS (process/file/network). Nothing ran. If the blocked word was meant as a plain variable (`lines = 27`), have the assistant rename it and retry — the gate matches words (see [The OS-access gate](os-access-gate.md)). If you trust the code, set `MACAULAY2_MCP_OS_ALLOW=<symbol>,<symbol>` in the server's environment and restart the client. |
| Server won't start in a GUI app (LM Studio, Claude Desktop) | try plain `uvx` first (recent versions resolve your shell PATH); if it won't start, put the absolute path from `which uvx` in the `command` field. For LM Studio you can watch the server's log in the Program tab's server detail view. |
| Running on Windows | v0.1 supports macOS and Ubuntu only; Windows is untested and unsupported. Open an issue if you need it — demand shapes the roadmap. |
