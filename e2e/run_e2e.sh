#!/usr/bin/env bash
# End-to-end demo: opencode + a small local LLM (Ollama) driving the
# macaulay2 MCP server, with Docker.
#
# Opt-in by design: it downloads a multi-GB model and is meant for
# demonstrating/validating the server, not for the default test suite.
#
# GPU handling, auto-detected (override: E2E_OLLAMA_MODE=container|native|gpu):
#   native     macOS + Ollama installed on the HOST -> Apple Silicon Metal.
#              The agent container talks to http://host.docker.internal:11434
#              (Docker containers on Mac cannot use the GPU themselves).
#   gpu        Linux with nvidia-smi -> Ollama container with GPU passthrough.
#   container  fallback (works everywhere): Ollama in Docker, CPU-only.
#
# Environment:
#   E2E_MODEL     ollama model tag (default: qwen3:4b)
#   E2E_ATTEMPTS  how many retries (small models are flaky; default 3)
#
# Outputs land in e2e/results/ (transcripts + logs).
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${E2E_MODEL:-qwen3:4b}"
ATTEMPTS="${E2E_ATTEMPTS:-3}"
MODE="${E2E_OLLAMA_MODE:-auto}"

detect_mode() {
  case "$(uname -s)" in
    Darwin)
      if command -v ollama >/dev/null 2>&1; then MODE=native; else MODE=container; fi ;;
    Linux)
      if command -v nvidia-smi >/dev/null 2>&1; then MODE=gpu; else MODE=container; fi ;;
    *) MODE=container ;;
  esac
}
if [ "$MODE" = "auto" ]; then detect_mode; fi
echo "==> Ollama mode: ${MODE} (override with E2E_OLLAMA_MODE=container|native|gpu)"

COMPOSE=(docker compose -f docker-compose.yml)
NATIVE=0
case "$MODE" in
  native)
    if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      echo "!! Host Ollama is not reachable on :11434." >&2
      echo "   Start it (open the Ollama app, or run 'ollama serve') and retry," >&2
      echo "   or use the CPU container instead: E2E_OLLAMA_MODE=container ./run_e2e.sh" >&2
      exit 1
    fi
    # free the port from a previous container-mode run, if any
    docker compose stop ollama >/dev/null 2>&1 || true
    if ! ollama list 2>/dev/null | grep -q "^${MODEL} "; then
      echo "==> Pulling ${MODEL} into host Ollama (Metal)"
      ollama pull "${MODEL}"
    fi
    NATIVE=1
    ;;
  gpu)
    COMPOSE+=( -f docker-compose.gpu.yml )
    echo "==> Starting Ollama container with NVIDIA GPU passthrough"
    "${COMPOSE[@]}" up -d ollama
    ;;
  container)
    echo "==> Starting Ollama container (CPU)"
    "${COMPOSE[@]}" up -d ollama
    ;;
  *)
    echo "!! Unknown E2E_OLLAMA_MODE=${MODE} (use container|native|gpu)" >&2
    exit 2
    ;;
esac

if [ "$MODE" != "native" ]; then
  echo "==> Waiting for Ollama"
  for _ in $(seq 1 90); do
    if "${COMPOSE[@]}" exec -T ollama ollama list >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  echo "==> Ensuring model ${MODEL} is available (downloads on first run)"
  if ! "${COMPOSE[@]}" exec -T ollama ollama list 2>/dev/null | grep -q "^${MODEL} "; then
    "${COMPOSE[@]}" exec -T ollama ollama pull "${MODEL}"
  fi
fi

echo "==> Building agent image"
docker compose build agent

mkdir -p results
status=1
for attempt in $(seq 1 "${ATTEMPTS}"); do
  echo
  echo "==> Attempt ${attempt}/${ATTEMPTS}"
  # opencode run --format json: one JSON event per line (tool calls with
  # their full outputs + the assistant's final text) -> assert.py checks
  # the SERVER's tool results hard and the MODEL's answer softly.
  if [ "$NATIVE" = "1" ]; then
    # swap in the provider config pointing at host Ollama (Metal); the task
    # text is passed as a positional arg so no shell re-interprets it
    run_ok=0
    docker compose run --rm agent sh -c \
      'cp /workspace/m2-mcp/e2e/opencode.native.json /workspace/opencode.json && exec opencode run --auto --print-logs --format json "$1"' \
      _ "$(cat task.txt)" \
      > "results/events-${attempt}.jsonl" 2> "results/stderr-${attempt}.log" || run_ok=1
  else
    run_ok=0
    docker compose run --rm agent \
      opencode run --auto --print-logs --format json "$(cat task.txt)" \
      > "results/events-${attempt}.jsonl" 2> "results/stderr-${attempt}.log" || run_ok=1
  fi
  if [ "$run_ok" = "1" ]; then
    echo "!! opencode run exited non-zero (see results/stderr-${attempt}.log)"
    continue
  fi
  echo "==> Asserting run"
  if python3 assert.py "results/events-${attempt}.jsonl"; then
    cp "results/events-${attempt}.jsonl" results/events.jsonl
    status=0
    break
  fi
done

if [ "${status}" -ne 0 ]; then
  echo
  echo "E2E FAILED after ${ATTEMPTS} attempts. Inspect e2e/results/."
  exit 1
fi
echo
echo "E2E PASSED (mode: ${MODE}, model: ${MODEL}). Full event log: e2e/results/events.jsonl"
