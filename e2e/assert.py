"""Assert that an E2E run shows the Macaulay2 MCP server was used correctly.

Usage: python3 assert.py <events-jsonl>

Input is `opencode run --format json` output: one JSON event per line.
The checks separate two responsibilities:

* THE SERVER (must be right, deterministic): the m2_evaluate tool results
  — found in tool_use events' state.output — must contain the real
  computation (Groebner basis and Betti table).
* THE MODEL (best effort, small-LLM quality): the assistant's final text
  answer should report the Groebner basis. Faithfully transcribing the
  Betti table from the tool output is reported but not required — 4B
  models compress "1 4 4 1" into "4"; see the larger-model comparison runs.
"""

import json
import re
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    events = []
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    tool_outputs = []
    tool_names = []
    for ev in events:
        if ev.get("type") != "tool_use":
            continue
        part = ev.get("part", {})
        if part.get("type") != "tool" or not str(part.get("tool", "")).startswith("macaulay2_"):
            continue
        tool_names.append(part.get("tool"))
        state = part.get("state", {})
        if state.get("status") == "completed":
            tool_outputs.append(str(state.get("output", "")))
    tools_blob = "\n".join(tool_outputs)

    answer = "\n".join(
        str(ev.get("part", {}).get("text", "")) for ev in events if ev.get("type") == "text"
    )

    hard = [
        ("m2_evaluate tool was called (completed)", "macaulay2_m2_evaluate" in tool_names),
        (
            "SERVER: Groebner basis in tool output (xy - z)",
            ("xy-z" in tools_blob) or re.search(r"xy\s*-\s*z", tools_blob) is not None,
        ),
        (
            "SERVER: Betti total row in tool output (1 4 4 1)",
            re.search(r"1\s+4\s+4\s+1", tools_blob) is not None,
        ),
        (
            "MODEL: final answer mentions the Groebner basis",
            "roebner" in answer,
        ),
    ]
    soft = [
        (
            "final answer transcribes the Betti row (small-LLM fidelity)",
            re.search(r"1\s+4\s+4\s+1", answer) is not None,
        ),
    ]

    failed = []
    for name, ok in hard:
        print(("PASS" if ok else "FAIL") + f" - {name}")
        if not ok:
            failed.append(name)
    for name, ok in soft:
        print(("soft PASS" if ok else "soft FAIL") + f" - {name}")

    if failed:
        print("\nE2E FAILED:", ", ".join(failed))
        return 1
    print("\nE2E PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
