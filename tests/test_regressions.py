"""Regression tests: every case here was a wrong answer at some point.

    python -m unittest discover tests

The synthetic-site tests always run. The Dupaco tests need the supplied snapshots (unpacked
into snapshots/ by the first harness run) and are skipped without them.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "solution"), str(ROOT / "harness")]
import solution  # noqa: E402
from kb.dates import as_of_date  # noqa: E402
from run_eval import load_snapshots  # noqa: E402
from scoring import _numbers, contains, score_conflicts, score_item  # noqa: E402

SELFTEST = ROOT / "harness" / "selftest"
DUPACO = ROOT / "snapshots"


def build(folder: Path):
    ks = solution.build()
    for snap in load_snapshots(folder):
        ks.ingest(snap)
    return ks


class AsOfDate(unittest.TestCase):
    def test_formats(self):
        for given, want in [("2026-05-31", "2026-05-31"), ("2026-05-31T12:00:00", "2026-05-31"),
                            ("05/31/2026", "2026-05-31"), ("May 31, 2026", "2026-05-31"),
                            ("2026-05", "2026-05-31"), ("May 2026", "2026-05-31"),
                            ("not a date", None), ("", None), (None, None)]:
            self.assertEqual(as_of_date(given), want, given)


class SyntheticSite(unittest.TestCase):
    """The kit's fictional site: different URLs and prose-style rates."""

    @classmethod
    def setUpClass(cls):
        cls.ks = build(SELFTEST / "snapshots")

    def test_eval_items(self):
        for line in (SELFTEST / "eval.jsonl").read_text().splitlines():
            item = json.loads(line)
            ans = self.ks.answer(item["question"], item.get("as_of"))
            self.assertEqual(score_item(item, ans)["correctness"], 1.0, item["question"])

    def test_conflicts(self):
        gold = json.loads((SELFTEST / "conflicts_gold.json").read_text())
        report = score_conflicts(gold, self.ks.conflicts())
        self.assertEqual((report["f1"], report["resolution_accuracy"]), (1.0, 1.0))


@unittest.skipUnless(any(DUPACO.glob("*/manifest.json")), "supplied snapshots not present")
class Dupaco(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ks = build(DUPACO)

    def says(self, question, want, never=(), as_of=None):
        ans = self.ks.answer(question, as_of)
        self.assertTrue(contains(ans.text, want), f"{question!r}: expected {want} in {ans.text!r}")
        for bad in never:
            self.assertFalse(contains(ans.text, bad), f"{question!r}: {bad} must not be in {ans.text!r}")
        return ans

    def declines(self, question, as_of=None):
        ans = self.ks.answer(question, as_of)
        self.assertFalse(ans.confident, f"{question!r} answered: {ans.text!r}")
        self.assertFalse(_numbers(ans.text), f"{question!r}: a refusal must not contain numbers")

    # -- tiers ------------------------------------------------------------------------------
    def test_loan_amount_picks_the_tightest_tier(self):
        self.says("What is the 30 year fixed mortgage rate for a $250,000 loan?", "7.32%", never=["7.29%", "7.34%"])

    def test_balance_decides_jumbo(self):
        self.says("I have $150,000 for the 10-month certificate special, what APY do I get?", "4.00%", never=["3.90%"])
        self.says("What is the APY on the 10-month certificate special with $5,000?", "3.90%", never=["4.00%"])

    def test_amount_written_with_k(self):
        self.says("With $15k in Share Savings what dividend rate do I get?", "0.15%")

    def test_new_car_is_the_newest_model_year_band(self):
        self.says("What's the APR on a brand new car loan for 60 months?", "5.39%", never=["5.64%", "6.34%"])

    def test_model_year_without_the_word_car(self):
        self.says("Rate for a 2022 SUV on a six-year loan?", "5.79%")
        self.says("I want to buy a 2026 Honda Civic, what is the 60 month rate?", "5.39%")

    def test_superlative(self):
        self.says("What's the highest certificate rate you offer?", "4.10%")

    def test_same_product_two_wordings(self):
        self.says("What does the HSA pay on $12,000?", "0.30%")
        self.says("What is the health savings account APY on $12,000?", "0.30%")

    # -- time -------------------------------------------------------------------------------
    def test_mortgage_apr_is_not_the_points_column(self):
        self.says("What is the 30-year fixed mortgage APR?", "6.186%", never=["0.00%"], as_of="2026-05-15")

    def test_as_of_month(self):
        q = "What is the 60 month auto loan APR for a 2025 car?"
        self.says(q, "5.19%", never=["5.39%"], as_of="May 2026")
        self.says(q, "5.39%", never=["5.19%"])

    def test_as_of_before_the_first_snapshot_is_flagged(self):
        ans = self.ks.answer("What is the 60 month auto loan APR for a 2025 car?", "2025-01-01")
        self.assertIn("earliest", ans.conflict_note or "")

    def test_withdrawn_offer(self):
        q = "What is the mortgage rate relief program rate?"
        self.says(q, "5.125%", as_of="2026-05-15")
        self.declines(q)

    # -- honest refusals --------------------------------------------------------------------
    def test_term_the_product_does_not_list(self):
        self.declines("What is the rate on a 10-year mortgage?")
        self.declines("Do you offer a 40-year mortgage?")

    def test_unknown_branch(self):
        self.declines("what are the lobby hours for the mullan avenue branch")
        self.declines("What are the hours for the Key West branch?")

    # -- company facts ----------------------------------------------------------------------
    def test_company_stats_reworded(self):
        self.says("How many Dupaco branches are there?", "22 branch")
        self.says("How many people belong to Dupaco?", "181,000")

    # -- sources and conflicts --------------------------------------------------------------
    def test_product_page_is_cited(self):
        ans = self.ks.answer("What's the APR for a 60-month auto loan on a 2025 model-year vehicle?")
        self.assertIn("https://www.dupaco.com/personal/loans/auto-motorcycle-loans", [s.url for s in ans.sources])

    def test_conflicts(self):
        found = self.ks.conflicts()
        topics = [c.topic for c in found]
        self.assertTrue(any("30-year mortgage" in t for t in topics), "mortgage rate changes are missing")
        for c in found:
            self.assertIn(c.resolution, c.values, c.topic)
            self.assertFalse({"0.35%", "3.25%"} <= set(c.values), "two money market products merged")

    def test_same_question_same_answer(self):
        fresh = build(DUPACO)
        for q in ("What is the 30-year mortgage rate?", "Who can join Dupaco?", "What are your lobby hours?"):
            self.assertEqual(self.ks.answer(q).text, fresh.answer(q).text, q)


if __name__ == "__main__":
    unittest.main()
