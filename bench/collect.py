#!/usr/bin/env python3
"""Score one bench run (opencode --format json event log) into results/bench.csv.

Columns record raw evidence verbatim: every distinct M2 code string the model
sent, the exact final answer, plus pass/fail checks and hygiene metrics
(repeated identical calls, absorbed errors, degree-claim honesty).
Usage: collect.py <events.jsonl> <model> <task> <attempt>
"""
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "results", "bench.csv")
MODELS_CSV = os.path.join(HERE, "results", "models.csv")

FIELDS = [
    "date", "model", "arch", "parameters", "quantization", "context", "pulled_date",
    "task", "attempt", "result",
    "m2_calls", "distinct_code_calls", "repeated_calls", "errors_in_outputs",
    "gb_shown", "betti_shown", "dim_shown",
    "parts_in_final", "deg_claimed", "deg_claim_in_tools",
    "failing_checks", "m2_code_calls_json", "final_answer",
]


def model_meta(model: str) -> dict:
    try:
        with open(MODELS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                if row["model"] == model:
                    return row
    except FileNotFoundError:
        pass
    return {"arch": "?", "parameters": "?", "quantization": "?", "context": "?"}


def evaluate(path: str, model: str, task: str, attempt: str) -> dict:
    codes: list[str] = []
    outputs: list[str] = []
    texts: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = ev.get("part", {})
            if ev.get("type") == "tool_use" and "macaulay2" in str(part.get("tool", "")):
                st = part.get("state", {})
                inp = st.get("input") or {}
                if isinstance(inp.get("code"), str):
                    codes.append(inp["code"])
                    outputs.append(str(st.get("output") or ""))
            elif ev.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])

    blob = "\n".join(outputs)
    final = texts[-1] if texts else ""
    compact = re.sub(r"\s+", "", blob)
    final_l = final.lower()

    checks = {
        "gb_shown": ("xy-z" in compact) or bool(re.search(r"xy\s*-\s*z", blob)),
        "betti_shown": bool(re.search(r"total:\s*1\s+4\s+4\s+1", blob)),
        # either an explicit "dim ... = 1" line, or a value-only echo: an i-line
        # containing 'dim' followed by 'oN : 1' (bare result printing)
        "dim_shown": bool(
            re.search(r"dim[^\n=]*=\s*1\b", blob)
            or re.search(r"dim[^\n]*\n+\s*o\d+\s*[:=]\s*1\b", blob)
            or re.search(r"dim[^\n]*\n+\s*1\b", blob)
        ),
    }
    checks["parts_in_final"] = bool(
        "xy" in final_l
        and re.search(r"1\s*4\s*4\s*1", final_l)
        and re.search(r"dim", final_l) and re.search(r"\b1\b", final_l)
    )
    deg = re.search(r"deg[^\d\n]{0,10}(\d+)", final_l)
    deg_claimed = deg.group(1) if deg else ""
    deg_in_tools = (not deg) or (deg_claimed in re.findall(r"\d+", blob))
    checks["deg_claim_in_tools"] = deg_in_tools

    failing = [k for k, v in checks.items() if not v]
    result = "PASS" if not failing else "FAIL"

    seen: dict[str, int] = {}
    for c in codes:
        seen[c] = seen.get(c, 0) + 1

    row = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model, "task": task, "attempt": attempt, "result": result,
        **model_meta(model),
        "m2_calls": len(codes),
        "distinct_code_calls": len(seen),
        "repeated_calls": sum(n - 1 for n in seen.values()),
        "errors_in_outputs": sum("error:" in o.lower() for o in outputs),
        "gb_shown": checks["gb_shown"], "betti_shown": checks["betti_shown"],
        "dim_shown": checks["dim_shown"], "parts_in_final": checks["parts_in_final"],
        "deg_claimed": deg_claimed, "deg_claim_in_tools": deg_in_tools,
        "failing_checks": "|".join(failing),
        "m2_code_calls_json": json.dumps(list(seen.keys()), ensure_ascii=False),
        "final_answer": final,
    }

    return row


def main() -> int:
    path, model, task, attempt = sys.argv[1:5]
    row = evaluate(path, model, task, attempt)
    new_file = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)
    print(f"  {row['result']}  {model} {task} #{attempt}  calls={row['m2_calls']} "
          f"errors={row['errors_in_outputs']} failing=[{row['failing_checks']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
