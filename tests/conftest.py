"""Test-session defaults.

Client-level tests spawn real `python -m macaulay2_mcp` servers whose cwd is
the repo root; without this they would write journal files into the working
tree. Individual journal tests re-enable it via StdioServerParameters(env=...).
"""

import os

os.environ.setdefault("MACAULAY2_MCP_JOURNAL", "off")
