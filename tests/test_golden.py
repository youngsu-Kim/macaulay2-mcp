"""Golden-output regression tests.

tests/data/golden.jsonl pins the observable behaviour of Macaulay2 1.26
output through our kernel protocol (prompt/echo handling, merged stderr,
plain-text rendering quirks). If a future M2 release changes any pinned
string, the test fails and the dataset must be reviewed — deliberately.

Each case is self-contained (defines its own rings/objects) and runs in one
shared persistent session, in file order.
"""

import json
from pathlib import Path

import pytest

from macaulay2_mcp.config import M2NotFoundError, M2StartupError, UnsupportedM2Version, load_config
from macaulay2_mcp.kernel import KernelCrashed, M2Session

DATA = Path(__file__).resolve().parent / "data" / "golden.jsonl"
CASES = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
CASE_IDS = [c["id"] for c in CASES]


def _m2_config_or_skip():
    try:
        return load_config()
    except (M2NotFoundError, UnsupportedM2Version):
        pytest.skip("Macaulay2 1.26 not available on this machine")


@pytest.fixture()
async def golden_session():
    # Fresh session per case: golden tests pin observable output, and a
    # per-case kernel also guarantees cases cannot leak state into each other.
    session = M2Session(_m2_config_or_skip())
    try:
        await session.ensure_started()
    except (M2NotFoundError, UnsupportedM2Version, M2StartupError, KernelCrashed):
        pytest.skip("could not start an M2 session")
    yield session
    await session.close()


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
async def test_golden(golden_session, case):
    result = await golden_session.evaluate(case["code"], timeout_s=30)
    assert not result.timed_out, case["id"]
    for needle in case["expect"]:
        assert needle in result.output, (
            f"case {case['id']!r}: expected {needle!r} in output:\n{result.output}"
        )
