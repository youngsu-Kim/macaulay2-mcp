# Installing Macaulay2 (details)

← back to the [README](../README.md)

The [Installation](../README.md#installation) section carries the two
one-line prerequisites and the client snippets; this file keeps the detail
that lives there on purpose.

## Which M2 to install

| OS | Command |
|---|---|
| macOS (Homebrew) | `brew install Macaulay2/tap/macaulay2` (the tap also exposes `M2` as an alias; `brew trust Macaulay2/tap` first on very recent Homebrew) |
| Ubuntu (official M2 PPA — always latest) | `sudo add-apt-repository ppa:macaulay2/macaulay2 && sudo apt install macaulay2` |
| Windows | Not supported in v0.1 (macOS and Ubuntu are the tested platforms; WSL2 untested) |

## Why a tap / PPA, and how to undo it

Both prereq commands add a package repository maintained by the Macaulay2
developers (a Homebrew *tap* / an APT *PPA*) — needed because `macaulay2` is
not in Homebrew core and Ubuntu's own package is outdated. Recent Homebrew
versions ask to *trust* a third-party tap before installing from it; trust
entries live in `~/.homebrew/trust.json` and are reversible at any time:

```sh
brew untrust --tap Macaulay2/tap                     # drop trust
brew untap Macaulay2/tap                             # remove the tap (after brew uninstall macaulay2)
sudo add-apt-repository --remove ppa:macaulay2/macaulay2   # remove the PPA
```

## uv itself

On macOS the official uv script
(`curl -LsSf https://astral.sh/uv/install.sh | sh`, installing to
`~/.local/bin`) works equally well — the README's snippets use plain `uvx`,
so either install route is fine.

## Environment settings

If M2 lives in a non-standard place, set `M2_BIN=/path/to/M2` in the
client's environment for the server. The only other settings are
`MACAULAY2_MCP_JOURNAL` (journal location / `off`, see
[Reading the journal](journal.md)) and `MACAULAY2_MCP_OS_ALLOW`
(comma-separated M2 OS-symbols to unblock, see
[The OS-access gate](os-access-gate.md)); v0.1 intentionally has no others.
