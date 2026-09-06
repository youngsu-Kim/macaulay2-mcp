"""Gatekeeping: refuse M2 calls that reach outside the interpreter.

Rationale
---------
This MCP server executes arbitrary M2 code chosen by an LLM on the user's
machine. Some M2 functions touch the operating system — run programs, open
files, read the environment, or kill the kernel. The functions below are
refused *before anything is sent to M2* (nothing runs, session untouched),
unless the user opts specific symbols in via the environment variable
``MACAULAY2_MCP_OS_ALLOW`` (comma-separated list of symbols).

Symbol list verified against Macaulay2 1.26.06 (Homebrew): symbols that do
not exist in this build are kept anyway so the list stays correct for other
distributions/builds. Absent here: system, netFetch, netRead, ftpGet,
openSocket, startServer, stopServer, getEnvironment, deleteFile, readFile,
writeFile, renameFile, useURL, exportVars.

HONESTY NOTE: this is *friction against accidents, not a sandbox*. M2's
``value("...")`` string-evaluation can construct any call dynamically and is
NOT blocked (blocking it breaks legitimate metaprogramming). If you need
isolation from a hostile caller, run the server in a container/VM — see the
README security section.
"""

from __future__ import annotations

import os
import re

from .scanner import mask

# Symbols that trigger process execution, network access, filesystem access,
# environment disclosure, or session destruction.
OS_SYMBOLS: frozenset[str] = frozenset(
    {
        # process execution / program probing
        "system",
        "runProgram",
        "findProgram",
        "checkProgramPath",
        # network
        "netFetch",
        "netRead",
        "ftpGet",
        "openSocket",
        "startServer",
        "stopServer",
        "useURL",
        # filesystem reads
        "lines",
        "readFile",
        "openIn",
        # filesystem writes / mutation
        "writeFile",
        "openOut",
        "deleteFile",
        "renameFile",
        "makeDirectory",
        "deleteDirectory",
        "installPackage",
        "exportVars",
        # environment / session control
        "getEnvironment",
        "currentDirectory",
        "quit",
        # viewer launch (opens a browser; confirmed present in 1.26.06)
        "viewHelp",
    }
)

_ALLOW_ENV = "MACAULAY2_MCP_OS_ALLOW"

_CATEGORIES = {
    "system": "process execution",
    "runProgram": "process execution",
    "findProgram": "program probing",
    "checkProgramPath": "program probing",
    "netFetch": "network access",
    "netRead": "network access",
    "ftpGet": "network access",
    "openSocket": "network access",
    "startServer": "network access",
    "stopServer": "network access",
    "useURL": "network access",
    "lines": "file read",
    "readFile": "file read",
    "openIn": "file read",
        "writeFile": "file write",
        "openOut": "file write",
    "deleteFile": "file mutation",
    "renameFile": "file mutation",
    "makeDirectory": "file mutation",
    "deleteDirectory": "file mutation",
    "installPackage": "package install (disk write)",
    "exportVars": "package export (disk write)",
        "getEnvironment": "environment disclosure",
        "currentDirectory": "environment disclosure",
        "quit": "session destruction",
        "viewHelp": "viewer/browser launch",
    }


def allowed_symbols() -> frozenset[str]:
    raw = os.environ.get(_ALLOW_ENV, "")
    return frozenset(tok.strip() for tok in raw.split(",") if tok.strip())


def find_blocked_calls(code: str) -> list[str]:
    """Return blocked OS-symbol mentions in ``code`` (sorted, unique).

    Matching runs on the *masked* text (string interiors and comments blanked)
    so that documentation, printed text, and comments mentioning e.g.
    ``runProgram`` do not trip the gate.
    """
    masked = mask(code).text
    allowed = allowed_symbols()
    hits: set[str] = set()
    for sym in OS_SYMBOLS - allowed:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(sym)}(?![A-Za-z0-9_])", masked):
            hits.add(sym)
    return sorted(hits)


def rejection_message(symbol: str) -> str:
    category = _CATEGORIES.get(symbol, "operating-system access")
    return (
        f"BLOCKED: the macaulay2-mcp gatekeeper refuses '{symbol}' ({category}).\n"
        f"Nothing was executed; the M2 session is untouched.\n"
        f"The gate is a guardrail against accidents, not a sandbox: M2's "
        f"value(\"...\") can still construct calls dynamically, so a determined "
        f"caller is not stopped — run this server in a container if you need "
        f"isolation.\n"
        f"If '{symbol}' is exactly what you need, the user can enable it by "
        f"setting the environment variable {_ALLOW_ENV} to include '{symbol}' "
        f"(e.g. {_ALLOW_ENV}=\"{symbol}\") for the server process, then "
        f"restarting the MCP client."
    )


def check_package_name(name: str) -> str | None:
    """Reject package names that are really file paths (load-smuggling)."""
    name = name.strip()
    if "/" in name or "\\" in name or name.lower().endswith(".m2"):
        return (
            f"BLOCKED: package name {name!r} looks like a file path; the "
            f"gatekeeper only accepts bare package names (e.g. \"BoijSoederberg\"). "
            f"To load definitions from a specific file, use m2_import_file with "
            f"an absolute path — its contents go through the same OS-call gate."
        )
    return None
