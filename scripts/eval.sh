#!/usr/bin/env bash
# Run the official scorer against our submission from the repo root.
# Usage: scripts/eval.sh [submission_folder] [extra run_eval args...]
set -euo pipefail
cd "$(dirname "$0")/.."
SUB="${1:-solution}"; shift || true
PY="${PYTHON:-python3.11}"
"$PY" harness/run_eval.py --submission "$SUB" --eval eval/public_eval.jsonl \
  --conflicts-gold harness/selftest/conflicts_gold.json --out "results/$(basename "$SUB")" "$@"
