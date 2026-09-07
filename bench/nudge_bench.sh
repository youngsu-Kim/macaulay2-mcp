#!/usr/bin/env bash
# Patient-user emulation: one-shot run (task-a), then continue the SAME session
# with a nudge listing what is still missing. Scores the COMBINED events.
# Usage: ./nudge_bench.sh <model> [attempts]
set -u
cd "$(dirname "$0")"
MODEL="${1:?model required}"; ATTEMPTS="${2:-3}"
PROMPT_A="$(cat task-a.txt)"
NUDGE="You stopped before answering all parts. List which of (a), (b), (c) are still unanswered, then complete only those, one m2_evaluate per part, checking that each output actually displays the result."
mkdir -p results/raw results/logs
CSV=results/nudge.csv
{ [ -f "$CSV" ] || echo "date,model,attempt,first_run_parts,after_nudge_parts,combined_result,gb_shown,betti_shown,dim_shown,final_pass,failing_checks"; } >> "$CSV"
for N in $(seq 1 "$ATTEMPTS"); do
  TAG="${MODEL//:/-}__nudge__${N}"
  echo "[$(date '+%F %T')] $TAG pass1"
  if ! timeout 900 opencode run --auto --format json -m "ollama/$MODEL" "$PROMPT_A" \
      > "results/raw/${TAG}.p1.jsonl" 2> "results/logs/${TAG}.p1.err"; then
    echo "  !! pass1 failed"; continue
  fi
  SID=$(python3 -c "
import json,sys
ids=[json.loads(l).get('sessionID') for l in open('results/raw/${TAG}.p1.jsonl') if l.strip()]
print(next((i for i in ids if i), ''))")
  [ -z "$SID" ] && { echo "  !! no session id"; continue; }
  echo "  session=$SID pass2"
  timeout 900 opencode run --auto --format json --session "$SID" "$NUDGE" \
      > "results/raw/${TAG}.p2.jsonl" 2> "results/logs/${TAG}.p2.err" || echo "  !! pass2 nonzero exit"
  cat "results/raw/${TAG}.p1.jsonl" "results/raw/${TAG}.p2.jsonl" > "results/raw/${TAG}.combined.jsonl"
  python3 - "$MODEL" "$N" "results/raw/${TAG}.p1.jsonl" "results/raw/${TAG}.combined.jsonl" <<'PYEOF'
import csv, sys
from datetime import datetime, timezone
from collect import evaluate
model, n, p1, comb = sys.argv[1:5]
r1, rc = evaluate(p1, model, "nudge-pre", "0"), evaluate(comb, model, "nudge", n)
shown = lambda r: "/".join(k[0] for k in ("gb_shown","betti_shown","dim_shown") if r[k]=="True")
row = [datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), model, n,
       shown(r1), shown(rc), rc["result"], rc["gb_shown"], rc["betti_shown"],
       rc["dim_shown"], rc["parts_in_final"], rc["failing_checks"]]
with open("results/nudge.csv","a",newline="") as f:
    csv.writer(f).writerow(row)
print(f"  pre={row[3]}  after={row[4]}  combined={rc['result']} fail=[{rc['failing_checks']}]")
PYEOF
done
echo "[$(date '+%F %T')] nudge bench done for $MODEL"
