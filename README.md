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

The scorer unpacks the zips into `snapshots/` the first time it runs. Other tools:
- `scripts/eval.sh` runs the public eval. `scripts/eval.sh solution selftest` runs the kit's
  synthetic site, including conflict scoring.
- `scripts/probe.py` asks our own questions, the ones outside the public set.
- `python -m unittest discover tests` runs the regression tests. `tests/` also holds a paraphrase
  set, a generated sweep over every rate row in every snapshot, and a load and odd-input test
  (see NOTES).
- `scripts/explore.py` browses the snapshots (`grep`, `history`, `diff`).

Results: public eval 0.89 (accuracy 0.89, consistency 1.00, speed 1.00, no stale values), and
1.00 on the self-test site. No API keys, standard library only.

Docs: [`solution/NOTES.md`](solution/NOTES.md) covers how it works, and
[`docs/RULES.md`](docs/RULES.md) has the "what is current" rules with evidence.
