#!/usr/bin/env bash
# e2e soak: for SOAK_HOURS hours, cycle the LaTeX-prompt task (with periodic
# M2-syntax control) across local models, recording per-cycle results in
# results/soak-summary.tsv. Between cycles it removes orphaned e2e-* Docker
# containers left by interrupted runs. It kills NOTHING on the host.
set -u
cd "$(dirname "$0")"

HOURS="${SOAK_HOURS:-3}"
END=$(( $(date +%s) + HOURS * 3600 ))
MODELS=(qwen3.5:4b qwen3.6:27b qwen3.8:27b)
TASKS=(task-latex.txt task.txt)   # round-robin all models per task before switching
SUM=results/soak-summary.tsv
mkdir -p results
[ -f "$SUM" ] || printf 'time\tmodel\ttask\tresult\tfailing_checks\n' > "$SUM"

cleanup_orphans() {
  local c
  for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep '^e2e-' || true); do
    echo "[$(date '+%F %T')] cleanup: removing container $c"
    docker rm -f "$c" >/dev/null 2>&1 || true
  done
}

i=0
while [ "$(date +%s)" -lt "$END" ]; do
  M="${MODELS[$(( i % ${#MODELS[@]} ))]}"
  T="${TASKS[$(( (i / ${#MODELS[@]}) % ${#TASKS[@]} ))]}"
  cleanup_orphans
  echo "=== cycle $i  model=$M  task=$T  $(date '+%F %T')"
  out=$(mktemp)
  if E2E_MODEL="$M" E2E_ATTEMPTS=1 TASK_FILE="$T" ./run_e2e.sh >"$out" 2>&1; then
    r=PASS
  else
    r=FAIL
  fi
  fails=$(grep '^FAIL -' "$out" | sed 's/^FAIL - //' | tr '\n' '|')
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$M" "$T" "$r" "$fails" >> "$SUM"
  echo "    -> $r  ${fails}"
  cp -f "results/events-1.jsonl" \
    "results/soak-$(date +%s)-${M//:/-}-${r}.jsonl" 2>/dev/null || true
  rm -f "$out"
  i=$(( i + 1 ))
done
echo "soak finished: $i cycles (window elapsed)"
