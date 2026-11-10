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
from kb import fees  # noqa: E402
from kb.dates import as_of_date  # noqa: E402
from kb.rates import _in_band  # noqa: E402
from kb.store import PageVersion, SnapshotView  # noqa: E402
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


class TierBoundaries(unittest.TestCase):
    """"$10,000 – $24,999.99" means 10,000 up to, not including, 25,000."""

    def test_single_amounts(self):
        inf = float("inf")
        for band, amount, inside in [
            ((10000, 24999.99), 10000, True), ((2500, 9999.99), 10000, False),       # lower edge
            ((10000, 24999.99), 24999.99, True), ((10000, 24999.99), 24999.5, True),
            ((10000, 24999.99), 25000, False), ((25000, inf), 25000, True),          # upper edge
            ((10000, 24999), 24999.5, True), ((25000, 39999), 25000, True),          # whole-dollar bands
            ((10000, 20000), 20000, True), ((20001, 50000), 20000, False), ((20001, 50000), 20001, True),
            ((0, 300000), 300000, True), ((0, 300000), 300001, False),               # "$300,000 or less"
            ((1000, inf), 999, False), ((100000, inf), 100000, True),                # minimum to earn
        ]:
            self.assertEqual(_in_band(band, (amount, amount)), inside, (band, amount))

    def test_a_range_names_a_tier_by_its_printed_ends(self):
        self.assertTrue(_in_band((10000, 24999.99), (10000, 24999)))
        self.assertTrue(_in_band((10000, 24999.99), (10000, 25000)))
        self.assertFalse(_in_band((2500, 9999.99), (10000, 24999)))
        self.assertFalse(_in_band((25000, float("inf")), (10000, 24999)))


def page(url, markdown, tier=3, title="Fee Schedule"):
    return PageVersion(url=url, key=url, title=title, markdown=markdown, snapshot_id="s1",
                       taken_on="2026-01-01", tier=tier, printed_date=None)


class Fees(unittest.TestCase):
    """Fee rows from the three layouts a site uses, on made-up pages (runs from a bare clone)."""

    TABLE = ("## Rate and Fee Schedule\n\n|Deposit Services Consumer|Col2|\n|---|---|\n"
             "|Stop payment (check, ACH, &amp; bill pay)|$30.00* per item|\n|Deposit Services Business||\n"
             "|Sweep Fee|$10.00* per month|\n|Teller and Cash Handling Service Charges||\n|Money orders|$5.00*each|\n"
             "\n---\n\n|Official check|$5.00* each|\n|---|---|\n"
             "|Incoming wire transfer|$10.00|\n|Domestic wire|$25.00 each|\n|International wire transfer|$55.00 each|\n")
    TEXT = ("Rate and Fee Schedule\n\nDeposit Services Consumer\nStop payment (check, ACH, & bill pay) $30.00\\* per item\n"
            "Consumer overdrafts (paid items) $30.00 per item\n_You will not be charged an overdraft fee if we pay an "
            "overdraft transaction that is less than $5.00._\nForeign currency exchange fee\n(includes Canadian checks) $35.00\n")
    PROSE = ("There is no annual fee. Other fees include: cash advance fee—$10.00 or 3.00% of the amount of each cash "
             "advance, whichever is greater; late payment fee is $15.00 or the minimum due; returned payment fee—up to $25. "
             "Offer valid only on the Platinum card.")

    def book(self, *pages):
        return fees.FeeBook(SnapshotView("s1", "2026-01-01", {p.key: p for p in pages}))

    def test_table_rows_with_sub_headings_and_a_data_row_as_header(self):
        got = {f.label: (f.amount, f.business) for f in fees.extract(page("https://x.test/fees.pdf", self.TABLE))}
        self.assertEqual(got["Stop payment (check, ACH, & bill pay)"], ("$30.00 per item", False))
        self.assertEqual(got["Sweep Fee"], ("$10.00 per month", True))            # under "Deposit Services Business"
        self.assertEqual(got["Official check"][0], "$5.00 each")                  # the second table's "header"

    def test_plain_text_rows_wrapped_labels_and_no_sentences(self):
        got = {f.label: f.amount for f in fees.extract(page("https://x.test/fees.pdf", self.TEXT))}
        self.assertEqual(got["Consumer overdrafts (paid items)"], "$30.00 per item")
        self.assertEqual(got["Foreign currency exchange fee (includes Canadian checks)"], "$35.00")
        self.assertFalse([l for l in got if l.startswith("You will not")])

    def test_disclosure_sentence(self):
        got = {f.label: f.amount for f in fees.extract(page("https://x.test/cards", self.PROSE, tier=4, title="Credit Cards"))}
        self.assertEqual(got["late payment fee"], "$15.00 or the minimum due")
        self.assertEqual(got["returned payment fee"], "up to $25")

    def test_blog_fees_are_not_facts(self):
        self.assertEqual(fees.extract(page("https://x.test/blog/fees", self.TABLE, tier=1)), [])

    def test_lookup_names_the_fee_or_its_family_or_nothing(self):
        book = self.book(page("https://x.test/fees.pdf", self.TABLE), page("https://x.test/cards", self.PROSE, tier=4))
        labels = lambda q: [f.label for f in book.lookup(q)]
        self.assertEqual(labels("How much is an international wire?"), ["International wire transfer"])
        self.assertEqual(labels("Is there a fee for an outgoing wire transfer?"),
                         ["Incoming wire transfer", "Domestic wire", "International wire transfer"])
        self.assertEqual(labels("What is the late payment fee on the Platinum card?"), ["late payment fee"])
        self.assertEqual(labels("What's the sweep fee for my business?"), ["Sweep Fee"])
        self.assertEqual(labels("What's the sweep fee?"), [])                      # a business fee, not asked as one
        self.assertEqual(labels("What is the annual fee?"), ["annual fee"])        # "There is no annual fee"
        self.assertIn("none", book.lookup("What is the annual fee?")[0].amount)
        self.assertEqual(labels("What's the fee for a returned check?"), [])       # not the "returned payment fee"
        self.assertEqual(labels("What is the fee for a paper statement?"), [])     # no such row: no answer

    def test_a_fee_is_not_moved_to_another_product(self):
        priced = {"auto", "mortgage", "platinum"}
        book = fees.FeeBook(SnapshotView("s1", "2026-01-01", {"c": page("https://x.test/cards", self.PROSE, tier=4)}),
                            product_of=lambda w: w if w in priced else None)
        self.assertEqual([f.label for f in book.lookup("What is the late payment fee on the Platinum card?")], ["late payment fee"])
        self.assertEqual(book.lookup("What's the late payment fee on my auto loan?"), [])


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

    def test_round_balance_is_the_tier_it_opens(self):
        self.says("What's the Share Savings APY on $10,000?", "0.15%", never=["0.10%"])
        self.says("What's the Share Savings APY on $25,000?", "0.20%", never=["0.15%"])
        self.says("What APY does High-Yield Savings pay on $100,000?", "1.85%", never=["1.50%"])
        self.says("Investor's Choice Money Market APY with a $25,000 balance?", "0.35%", never=["0.30%"])
        self.says("What's the APR on a $20,001 home improvement loan?", "8.75%", never=["8.50%"])
        self.says("What dividend rate do I earn on Share Savings with a balance between $10,000 and $24,999?", "0.15")

    def test_amounts_however_they_are_written(self):
        self.says("What does High-Yield Savings pay on $1 million?", "2.45%", never=["1.50%"])
        self.says("What does High-Yield Savings pay on 250000 dollars?", "2.05%", never=["1.50%"])
        self.says("What's the HSA APY if I keep just under $25,000?", "0.30%", never=["0.35%"])
        self.says("What's the Share Savings APY for a balance of at least $25,000?", "0.20%", never=["0.15%"])
        self.declines("What does Launchpad Savings pay on $1,500?")                       # the tier ends at $1,000

    def test_opening_minimum_is_not_a_rate(self):
        self.says("How much do I need to open a High-Yield Savings account?", "50,000", never=["1.50%"])

    def test_term_unit_is_not_a_product_word(self):
        self.says("I'm buying a 2025 Toyota — what's your 60 mo rate?", "5.39%", never=["6.74%"])

    def test_online_is_not_a_request_for_a_link(self):
        self.says("What is the APY on a Bright Savings online savings account?", "2.25%")
        self.says("How do I join Dupaco online?", "join.dupaco.com")
        self.says("Where can I see certificate rates online?", "dupaco.com/personal/savings-account")

    # -- fees -------------------------------------------------------------------------------
    def test_fees_come_from_fee_rows(self):
        self.says("How much is an international wire?", "$55.00", never=["$10.00", "$25.00"])
        self.says("What does a domestic wire cost?", "$25.00", as_of="2026-05-15")      # text-layout schedule
        self.says("What's the cash advance fee on the Platinum Visa?", "$10.00 or 3.00%", never=["2.90%"])
        self.says("What is the late payment fee on the Platinum Visa?", "$15.00", never=["$35.00"])
        self.says("What's the late fee on a business credit card?", "$35.00", never=["$15.00"])
        self.says("How much does a 6 month share certificate pay?", "3.40%")             # a rate, not a fee
        self.says("What is the fee for drilling a safe deposit box?", "$175.00", never=["$25.00"])
        self.says("What's the late fee on a safe deposit box?", "$10.00", never=["$25.00"])
        self.says("How much does it cost to rent a 5x10 safe deposit box?", "$60.00", never=["$25.00", "$40.00"])
        self.says("Is there an annual fee on the Platinum Visa?", "no annual fee", never=["2.90%"])
        self.says("How much is a cashier's check?", "$5.00")

    def test_a_fee_the_site_does_not_list_is_declined(self):
        for q in ("What's the late fee on my auto loan?", "What's the fee for a returned check?",
                  "How much is the mortgage application fee?", "What does it cost to order checks?"):
            self.declines(q)

    # -- time -------------------------------------------------------------------------------
    def test_mortgage_apr_is_not_the_points_column(self):
        self.says("What is the 30-year fixed mortgage APR?", "6.186%", never=["0.00%"], as_of="2026-05-15")

    def test_as_of_month(self):
        q = "What is the 60 month auto loan APR for a 2025 car?"
        self.says(q, "5.19%", never=["5.39%"], as_of="May 2026")
        self.says(q, "5.39%", never=["5.19%"])

    def test_date_written_in_the_question(self):
        self.says("What was the 60-month auto loan APR for a 2025 car as of May 2026?", "5.19%", never=["5.39%"])
        self.says("What was the 12-month certificate APY back in May 2026?", "2.90%", never=["3.40%"])
        # the as_of argument wins over the wording
        self.says("What was the 12-month certificate APY back in May 2026?", "3.40%", as_of="2026-09-28")

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

    def test_term_the_site_never_mentions(self):
        self.declines("What's the swift code for Dupaco?")

    def test_unfamiliar_words_do_not_cause_a_refusal(self):
        self.says("What's the APR for a pontoon boat loan of $45,000 for 120 months?", "9.34%")
        self.says("What's the APY on a rainy-day Share Savings account with $3,000?", "0.10%")
        self.says("What's the rate on a used car loan?", "5.39%")

    def test_interpreter_decides_what_the_rules_cannot_bind(self):
        """The optional second tier (kb/interpret.py), here with a stand-in for a model."""
        ks = build(DUPACO)
        asked = []

        def fake(question, catalog):
            asked.append(question)
            if "camper" in question:
                return {"product": "Boat & RV Loans"}
            if "premium" in question:
                return {"listed": False}
            if "abroad" in question:
                return {"fee": "International wire transfer"}
            if "bogus" in question:
                return {"product": "Not In The Catalog"}             # ignored: not a catalog entry
            raise RuntimeError("model unavailable")                  # ignored: the rules' answer stands

        ks.interpreter = fake
        self.assertTrue(contains(ks.answer("What's the APR on a camper loan for $30,000 over 60 months?").text, "7.09%"))
        self.assertFalse(ks.answer("How much does a premium money market account pay?").confident)
        self.assertTrue(contains(ks.answer("What is the fee to send money abroad?").text, "$55.00"))
        self.assertTrue(contains(ks.answer("What's the APR on a bogus pontoon boat loan of $45,000 for 120 months?").text, "9.34%"))
        self.assertTrue(contains(ks.answer("What's the APR for a pontoon boat loan of $45,000 for 120 months?").text, "9.34%"))
        # a question the rules bind completely never reaches the interpreter
        ks.answer("What is the APR on a 36-month personal loan?")
        self.assertFalse([q for q in asked if "36-month" in q])

    # -- branches ---------------------------------------------------------------------------
    def test_branch_outside_the_crawled_locator(self):
        ans = self.says("Is there a branch in Madison?", "Mineral Point")
        self.assertTrue(ans.confident)
        self.assertFalse(self.ks.answer("Is there a branch in Chicago?").confident)
        self.says("Does Dupaco have a location in Madison?", "Mineral Point", never=["151,000"])   # other wording
        self.says("is there a branch in waterloo?", "Mullan")                                      # lower case
        self.says("Do you have a branch in Asbury?", "closing")                           # closure outranks mentions
        self.says("What is the address of the Dyersville branch?", "807 Ninth St. SE")
        self.declines("What's the address of the Platteville branch?")                    # not an ATM's address
        self.says("What is the address of the Galena Branch?", "11375 Oldenburg")         # locator still first

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
