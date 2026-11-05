# Dupaco Knowledge System: interface.ai build assignment

A knowledge system that reads five snapshots of a credit-union website (May–Sep 2026) and
answers member questions with the **current**, correctly tiered value. It cites sources,
reports the contradictions it finds, and says "I don't know" when the site doesn't say.

- Submission: [`solution/`](solution/) (`solution.py` → `build()` → `ingest / answer / conflicts`)
- How it works: [`solution/NOTES.md`](solution/NOTES.md)
- Scorer and contract (supplied, unmodified): `harness/`, `eval/`, `starter/`

## Run

The website snapshots are **not** in this repo (they were shared for the assignment only).
Put the five supplied zips in `snapshots_zip/`, then from the repo root run:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r solution/requirements.txt
python harness/run_eval.py --submission solution --eval eval/public_eval.jsonl
```

The scorer unpacks the zips into `snapshots/` the first time it runs. `scripts/eval.sh` runs the
same command and also scores the conflict self-test. `scripts/explore.py` is a helper for
browsing the snapshots (`grep`, `history`, `diff`).
