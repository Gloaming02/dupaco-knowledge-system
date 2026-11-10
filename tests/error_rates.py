#!/usr/bin/env python3
"""Two error rates, not one score: answering wrongly and refusing wrongly cost the same on the
scorer but have different causes, so every change is judged on both.

    python tests/error_rates.py tests/dev_eval.jsonl tests/heldout_eval.jsonl [-v]

  wrong answer   a confident answer that misses the value, contains a forbidden one, or answers
                 a question the site cannot answer
  wrong refusal  "I don't know" to a question the site does answer
dev_eval.jsonl holds the wrong answers found in review (fair game to fix). heldout_eval.jsonl
was written before those fixes and is frozen: it is only ever run, never tuned against.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "solution"), str(ROOT / "harness")]
import solution  # noqa: E402
from run_eval import load_snapshots  # noqa: E402
from scoring import score_item  # noqa: E402


def main():
    verbose = "-v" in sys.argv
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    ks = solution.build()
    for snap in load_snapshots(ROOT / "snapshots"):
        ks.ingest(snap)
    for path in files:
        n = right = wrong_answer = wrong_refusal = 0
        for line in Path(path).read_text().splitlines():
            item = json.loads(line)
            ans = ks.answer(item["question"], item.get("as_of"))
            ok = score_item(item, ans)["correctness"] >= 0.999
            n += 1
            right += ok
            kind = "ok"
            if not ok:
                kind = "wrong refusal" if (not ans.confident and item["category"] != "should_refuse") else "wrong answer"
                wrong_refusal += kind == "wrong refusal"
                wrong_answer += kind == "wrong answer"
            if verbose and not ok:
                want = "REFUSE" if item["category"] == "should_refuse" else item["must_include"]
                print(f"  [{kind}] {item['question']}\n      want {want}\n      got  {ans.text[:150]}")
        print(f"{Path(path).name}: {right}/{n} right, {wrong_answer} wrong answers, {wrong_refusal} wrong refusals")


if __name__ == "__main__":
    main()
