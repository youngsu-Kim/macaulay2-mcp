#!/usr/bin/env bash
# Host-local model benchmark: opencode (host) + Ollama (Metal) + Macaulay2
# (host brew) + this repo's server. No Docker (that stays e2e's job).
#
#   ./run_bench.sh                                  # defaults below
#   MODELS="gemma4:e4b" ATTEMPTS=1 ./run_bench.sh  # subset / quick pass
#
# Results: results/bench.csv (verbatim code calls + final answers included),
# raw logs in results/raw/, stderr in results/logs/. Nothing is pushed.
set -u
cd "$(dirname "$0")"

MODELS="${MODELS:-qwen3:4b qwen3.5:4b qwen3:14b qwen3.6:27b qwen3.8:27b}"
TASKS="${TASKS:-task-a task-b}"
ATTEMPTS="${ATTEMPTS:-3}"
mkdir -p results/raw results/logs

# ---- models.csv snapshot: exact quantization, arch, context, pull date ----
python3 - "$MODELS" <<'PYEOF'
import csv, os, subprocess, sys, datetime
models = sys.argv[1].split()
rows = []
for m in models:
    if not os.environ.get("ALLOW_MISSING") and subprocess.run(
        ["ollama", "list"], capture_output=True, text=True
    ).stdout.find(m + " ") < 0:
        print(f"  (skip models.csv: {m} not pulled)")
        continue
    info = {"model": m, "arch": "?", "parameters": "?", "quantization": "?",
            "context": "?", "pulled_date": "?"}
    out = subprocess.run(["ollama", "show", m], capture_output=True, text=True).stdout
    seen = set()
    for line in out.splitlines():
        s = line.strip()
        for key, field in (("architecture", "arch"), ("parameters", "parameters"),
                           ("quantization", "quantization"), ("context length", "context")):
            if s.startswith(key) and key not in seen:
                seen.add(key)
                info[field] = s.split(key, 1)[-1].strip()
    name, _, tag = m.partition(":")
    man = os.path.expanduser(f"~/.ollama/models/manifests/registry.ollama.ai/library/{name}/{tag or 'latest'}")
    if os.path.exists(man):
        info["pulled_date"] = datetime.datetime.fromtimestamp(
            os.path.getmtime(man)).strftime("%Y-%m-%d")
    rows.append(info)
with open("results/models.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["model", "arch", "parameters", "quantization",
                                      "context", "pulled_date"])
    w.writeheader(); w.writerows(rows)
for r in rows:
    print(f"  {r['model']:<14} {r['arch']:<8} {r['parameters']:<6} {r['quantization']:<8} ctx={r['context']:<7} pulled={r['pulled_date']}")
PYEOF

# ---- main grid ----
if [ ! -f results/bench.csv ]; then
  echo "run log started $(date -u '+%Y-%m-%dT%H:%M:%SZ')  models=[$MODELS] tasks=[$TASKS] attempts=$ATTEMPTS" \
    > results/bench-run.log
fi
for M in $MODELS; do
  if ! ollama list | grep -q "^${M} "; then
    echo "SKIP $M (not pulled)"; continue
  fi
  for T in $TASKS; do
    for N in $(seq 1 "$ATTEMPTS"); do
      TAG="${M//:/-}__${T}__${N}"
      echo "[$(date '+%F %T')] $TAG"
      if ! timeout 900 opencode run --auto --format json -m "ollama/$M" \
           "$(cat "$T.txt")" > "results/raw/${TAG}.jsonl" 2> "results/logs/${TAG}.err"; then
        echo "  !! opencode exited non-zero (see results/logs/${TAG}.err)"
      fi
      python3 collect.py "results/raw/${TAG}.jsonl" "$M" "$T" "$N" \
        || echo "  !! collect failed for $TAG"
    done
  done
done
echo "[$(date '+%F %T')] bench grid finished"
