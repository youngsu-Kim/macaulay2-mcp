#!/usr/bin/env python3
"""Re-score all raw logs with the current collect.py checks (no model reruns)."""
import csv
import glob
import os

from collect import CSV_PATH, FIELDS, evaluate

rows = []
for path in sorted(glob.glob("results/raw/*__task-*__*.jsonl")):
    base = os.path.basename(path)[:-len(".jsonl")]
    model, task, attempt = base.rsplit("__", 2)
    model = model.replace("-", ":", 1)
    rows.append(evaluate(path, model, task, attempt))
rows.sort(key=lambda r: (r["model"], r["task"], int(r["attempt"])))
with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader(); w.writerows(rows)
print(f"rescored {len(rows)} cells")
from collections import Counter

print(Counter(r["result"] for r in rows))
for r in rows:
    print(f"{r['result']:4} {r['model']:12} {r['task']} #{r['attempt']} "
          f"calls={r['m2_calls']:>2} err={r['errors_in_outputs']:>2} fail=[{r['failing_checks']}]")
