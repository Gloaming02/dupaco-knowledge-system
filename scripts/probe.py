#!/usr/bin/env python3
"""Ask the solution ad-hoc questions (our own, not the eval set) to check it generalises.

  python3.11 scripts/probe.py                 # built-in probe list
  python3.11 scripts/probe.py "question" [as_of]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "solution"), str(ROOT / "harness")]
import solution  # noqa: E402
from run_eval import load_snapshots  # noqa: E402

PROBES = [
    ("What's the APY on a 12-month certificate?", None),
    ("12 month CD rate?", None),
    ("How much does a 6 month share certificate pay?", None),
    ("What is the 48-month auto loan rate for a 2019 car?", None),
    ("Auto loan rate for a 2016 vehicle, 48 months", None),
    ("What is the APR on a boat loan of $30,000 for 72 months?", None),
    ("What's the rate on a 15-year fixed mortgage?", None),
    ("What are the refinance rates for a 30-year mortgage?", None),
    ("What is the HELOC rate?", None),
    ("What's the rate on the Rewards Visa?", None),
    ("What dividend does High-Yield Savings pay on $50,000?", None),
    ("What is the APY on a Roth IRA 18-month certificate?", None),
    ("What is the business 60-month certificate rate?", None),
    ("What is the 17-month jumbo special APY?", None),
    ("What was the 10-month special certificate APY in June 2026?", "2026-06-15"),
    ("What was the 60-month auto loan APR for a 2025 car in May 2026?", "2026-05-20"),
    ("What rate do you offer on a balloon mortgage?", None),
    ("What's the rate on a jumbo 5-year ARM?", None),
    ("Do you have a rate for land loans?", None),
    ("What is the interest rate on a payday loan?", None),
]


def main():
    ks = solution.build()
    for s in load_snapshots(ROOT / "snapshots"):
        ks.ingest(s)
    probes = [(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)] if len(sys.argv) > 1 else PROBES
    for q, as_of in probes:
        t = time.time()
        a = ks.answer(q, as_of=as_of)
        src = a.sources[0].url.split(".com")[-1] if a.sources else "-"
        print(f"Q: {q}" + (f"  [as_of {as_of}]" if as_of else ""))
        print(f"   {'OK ' if a.confident else 'IDK'} {src}  ({(time.time()-t)*1000:.0f} ms)\n   {a.text[:300]}\n")


if __name__ == "__main__":
    main()
