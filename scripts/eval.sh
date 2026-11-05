#!/usr/bin/env bash
# Run the official scorer from the repo root.
#   scripts/eval.sh [submission]            public eval (40 questions; no conflict gold is shipped for it)
#   scripts/eval.sh [submission] selftest   the kit's tiny synthetic site, incl. conflict scoring
set -euo pipefail
cd "$(dirname "$0")/.."
SUB="${1:-solution}"
PY="${PYTHON:-python3.11}"
if [ "${2:-}" = "selftest" ]; then
  "$PY" harness/run_eval.py --submission "$SUB" --snapshots harness/selftest/snapshots \
    --eval harness/selftest/eval.jsonl --conflicts-gold harness/selftest/conflicts_gold.json \
    --out "results/selftest"
else
  "$PY" harness/run_eval.py --submission "$SUB" --eval eval/public_eval.jsonl --out "results/$(basename "$SUB")"
fi
