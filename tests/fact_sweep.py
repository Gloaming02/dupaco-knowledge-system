#!/usr/bin/env python3
"""Generated stress test: for every rate-sheet row in every snapshot, ask a natural question
built from that row (with as_of = that snapshot's date) and check that
  - the row's value is in the answer, and
  - no *other snapshot's* value for the same row is in the answer (a stale value).
Rows whose value never changed can't produce a stale hit, so they test retrieval only.

  python3.11 tests/fact_sweep.py
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "solution"), str(ROOT / "harness")]
import solution  # noqa: E402
from run_eval import load_snapshots  # noqa: E402
from scoring import contains  # noqa: E402
from kb.conflicts import family  # noqa: E402


def question(f, fam_label):
    """A member-style question that pins the row down by its qualifiers."""
    bits = []
    if f.audience == "business":
        bits.append("business")
    if f.ira_kind:
        bits.append(f"{f.ira_kind} IRA")
    if f.term:
        bits.append(f"{f.term // 12}-year" if f.term >= 120 and f.term % 12 == 0 else f"{f.term}-month")
    if "jumbo" in f.flags:
        bits.append("jumbo")
    if "special" in f.flags and "certificate" in fam_label:
        bits.append("special")
    if "refinance" in f.flags:
        bits.append("refinance")
    bits.append(fam_label.replace("certificate special", "certificate"))
    q = "What is the " + " ".join(bits)
    if f.years:
        q += f" for a {f.years[1]} model-year vehicle"
    if f.amount:
        lo, hi = f.amount
        if hi != float("inf") and lo > 0:
            q += f" with a balance of ${(lo + hi) / 2:,.0f}"
        elif hi == float("inf") and lo >= 1000 and "jumbo" not in f.flags:
            q += f" with ${lo * 1.5:,.0f}"
        elif lo == 0 and hi != float("inf"):
            q += f" for ${hi * 0.9:,.0f}"
    metric = "APR" if f.is_loan else "APY"
    return q + f" {metric}?", metric.lower()


def main():
    ks = solution.build()
    snaps = load_snapshots(ROOT / "snapshots")
    for s in snaps:
        ks.ingest(s)
    history = defaultdict(dict)                      # (page key, section, name) -> {snapshot: value}
    rows = []
    for view in ks.store.snapshots:
        for p in view.pages.values():
            if p.tier < 5 or p.carried:              # the rate sheet is the ground truth
                continue
            for f in p.facts:
                fam, label = family(f)
                if not fam or "intro" in f.flags:
                    continue
                q, metric = question(f, label)
                if metric not in f.values:
                    continue
                k = (p.key, f.section, f.name, f.term, f.years, f.amount)
                history[k][view.snapshot_id] = f.values[metric]
                rows.append((view, k, q, f.values[metric]))
    stats, fails = Counter(), []
    for view, k, q, want in rows:
        a = ks.answer(q, as_of=view.taken_on)
        stale = {v for sid, v in history[k].items() if sid != view.snapshot_id and v != want}
        ok = contains(a.text, want)
        bad = [v for v in stale if contains(a.text, v)]
        stats["asked"] += 1
        stats["value_found"] += ok
        stats["stale_hit"] += bool(bad)
        stats["changed_rows"] += bool(stale)
        if not ok or bad:
            fails.append((view.taken_on, q, want, bad, a.text[:160]))
    print(dict(stats))
    print(f"value found: {stats['value_found'] / stats['asked']:.1%}   stale hits: {stats['stale_hit']}")
    for f in fails[:25]:
        print("  ", f)


if __name__ == "__main__":
    main()
