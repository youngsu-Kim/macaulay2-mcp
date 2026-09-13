"""macaulay2-mcp: an MCP server for Macaulay2."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("macaulay2-mcp")
except PackageNotFoundError:  # running from a source tree without install metadata
    __version__ = "0.1.2"
