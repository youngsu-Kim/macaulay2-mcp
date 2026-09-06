#!/usr/bin/env bash
# End-to-end demo: opencode + a small local LLM (Ollama) driving the
# macaulay2 MCP server, all inside Docker.
#
# Opt-in by design: it downloads a multi-GB model and is meant for
# demonstrating/validating the server, not for the default test suite.
#
# Environment:
#   E2E_MODEL    ollama model tag (default: qwen3:4b)
#   E2E_ATTEMPTS how many times to retry (small models are flaky; default 3)
#
# Outputs land in e2e/results/ (transcripts + logs).
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${E2E_MODEL:-qwen3:4b}"
ATTEMPTS="${E2E_ATTEMPTS:-3}"

echo "==> Building agent image"
docker compose build agent

echo "==> Starting Ollama"
docker compose up -d ollama

echo "==> Waiting for Ollama"
for _ in $(seq 1 90); do
  if docker compose exec -T ollama ollama list >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "==> Ensuring model ${MODEL} is available (downloads on first run)"
if ! docker compose exec -T ollama ollama list 2>/dev/null | grep -q "^${MODEL} "; then
  docker compose exec -T ollama ollama pull "${MODEL}"
fi

mkdir -p results
status=1
for attempt in $(seq 1 "${ATTEMPTS}"); do
  echo
  echo "==> Attempt ${attempt}/${ATTEMPTS}"
  if docker compose run --rm agent \
      opencode run --auto --print-logs --format json "$(cat task.txt)" \
      > "results/events-${attempt}.jsonl" 2> "results/stderr-${attempt}.log"; then
    echo "==> Asserting run"
    if python3 assert.py "results/events-${attempt}.jsonl"; then
      cp "results/events-${attempt}.jsonl" results/events.jsonl
      status=0
      break
    fi
  else
    echo "!! opencode run exited non-zero (see results/stderr-${attempt}.log)"
  fi
done

if [ "${status}" -ne 0 ]; then
  echo
  echo "E2E FAILED after ${ATTEMPTS} attempts. Inspect e2e/results/."
  exit 1
fi
echo
echo "E2E PASSED. Full event log: e2e/results/events.jsonl"
