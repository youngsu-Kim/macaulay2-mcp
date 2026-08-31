"""Configuration for macaulay2-mcp.

v0.1 is deliberately low-knob: it targets Macaulay2 1.26 (the latest stable
release) and pins the kernel flags. The only user-facing setting is the
``M2_BIN`` environment variable, for installations in unusual locations.
Supporting other M2 versions is tracked for v0.2.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass

# Pinned: only Macaulay2 1.26.x (latest stable) is supported in v0.1.
SUPPORTED_M2_VERSIONS: tuple[int, int] = (1, 26)

# Pinned: flags used to start the M2 kernel in headless, non-interactive mode.
# Verified against M2 1.26.06: no banner (--silent), no user init (-q),
# errors print inline instead of opening the debugger (--no-debug),
# prompt-based protocol works over pipes (--no-tty).
M2_KERNEL_FLAGS: tuple[str, ...] = ("-q", "--no-debug", "--no-tty", "--silent")

# Author-set safety defaults: guard the shared M2 session against runaway or
# infinite computations. See the TIMED OUT message in kernel.py.
DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 3600

# How long to wait for a freshly started kernel to print its first prompt.
STARTUP_TIMEOUT_S = 30

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

_INSTALL_HINT = """Install Macaulay2 (latest stable):
  macOS:   brew install macaulay2
  Ubuntu:  sudo add-apt-repository ppa:macaulay2/macaulay2 && sudo apt install macaulay2
  Other:   https://macaulay2.com/Downloads/
If M2 is installed in a non-standard location, set the M2_BIN environment
variable to the full path of the executable."""


class M2NotFoundError(Exception):
    """The M2 executable could not be located."""


class UnsupportedM2Version(Exception):
    """The found M2 is not a supported version."""


class M2StartupError(Exception):
    """The M2 process failed to start."""


@dataclass(frozen=True)
class M2Config:
    binary: str
    version: tuple[int, int, int]
    version_raw: str

    @property
    def version_str(self) -> str:
        return self.version_raw

    def kernel_command(self) -> list[str]:
        return [self.binary, *M2_KERNEL_FLAGS]


def _parse_version(text: str) -> tuple[tuple[int, int, int], str] | None:
    m = _VERSION_RE.search(text)
    if not m:
        return None
    return (tuple(int(g) for g in m.groups()), m.group(0))  # type: ignore[return-value]


def discover_binary() -> str:
    """Locate the M2 executable.

    Order: M2_BIN environment variable, then ``M2``/``Macaulay2`` on PATH,
    then well-known package-manager install prefixes.
    """
    override = os.environ.get("M2_BIN", "").strip()
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        raise M2NotFoundError(
            f"M2_BIN is set to {override!r}, but that file does not exist or is not "
            f"executable. Point it at a Macaulay2 executable, or unset M2_BIN."
        )
    for name in ("M2", "Macaulay2"):
        found = shutil.which(name)
        if found:
            return found
    for path in (
        "/opt/homebrew/opt/macaulay2/bin/M2",
        "/usr/local/opt/macaulay2/bin/M2",
        "/opt/homebrew/bin/M2",
        "/usr/local/bin/M2",
    ):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise M2NotFoundError(
        "Macaulay2 (the 'M2' executable) was not found on this machine.\n\n" + _INSTALL_HINT
    )


def query_version(binary: str) -> tuple[tuple[int, int, int], str]:
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise M2StartupError(f"Could not run {binary!r} --version: {exc}") from exc
    parsed = _parse_version(proc.stdout or proc.stderr)
    if parsed is None:
        raise M2StartupError(
            f"{binary!r} does not look like Macaulay2 (no version string found; "
            f"output: {(proc.stdout or proc.stderr).strip()[:200]!r})."
        )
    return parsed


def load_config() -> M2Config:
    """Discover M2 and verify it is a supported version."""
    binary = discover_binary()
    version, version_raw = query_version(binary)
    major, minor = version[:2]
    if (major, minor) != SUPPORTED_M2_VERSIONS:
        raise UnsupportedM2Version(
            f"Found Macaulay2 {version_raw}, but this version of macaulay2-mcp only "
            f"supports 1.26.x (the latest stable release).\n\n"
            f"Please upgrade Macaulay2:\n"
            f"  macOS:   brew update && brew upgrade macaulay2\n"
            f"  Ubuntu:  sudo apt update && sudo apt install macaulay2\n"
            f"Support for other versions may arrive in a future release."
        )
    return M2Config(binary=binary, version=version, version_raw=version_raw)


def clamp_timeout(timeout_s: float) -> int:
    try:
        value = int(timeout_s)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return max(1, min(value, MAX_TIMEOUT_S))
