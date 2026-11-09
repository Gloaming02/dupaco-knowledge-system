"""Answer rate questions from structured facts.

1. Parse the question into the same fact-key fields (term, model year, amount, audience, variant).
2. Filter facts that contradict an explicit qualifier (hard constraints).
3. Score product similarity (IDF-weighted word overlap with synonyms).
4. Among the best-matching facts, the most authoritative page wins (R2), then the newest
   printed date (R3). Rows are only taken from that one page, so stale copies never
   leak into the answer.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Optional

from .authority import NAMES
from .facts import INF, MONEY_RANGE, RateFact, term_months


def authority_name(tier: int) -> str:
    return NAMES[tier]

RATE_INTENT = re.compile(r"\b(rates?|apys?|aprs?|interest|dividends?|yields?|earn|pays?|paying)\b|%", re.I)
# "Do you offer a 40-year mortgage?": a product with a term is a rate-table question too.
TERM_PRODUCT = re.compile(r"\b(?:do you (?:offer|have)|is there|are there)\b.*\b(?:mortgages?|loans?|certificates?|cds?)\b", re.I)
NOT_RATE = re.compile(r"\b(link|url|website|web page|webpage|where can i (?:see|find))\b", re.I)
WORD = re.compile(r"[a-z]+")
SYNONYMS = {
    "car": "auto", "cars": "auto", "vehicle": "auto", "vehicles": "auto", "automobile": "auto",
    "truck": "auto", "motorcycle": "auto", "suv": "auto", "sedan": "auto", "pickup": "auto",
    "cd": "certificate", "cds": "certificate", "certificates": "certificate", "term": "certificate",
    "mortgages": "mortgage",
    "card": "visa", "cards": "visa", "credit": "visa",
    "boat": "boat", "rv": "rv", "atv": "atv", "snowmobile": "atv",
}
# Words that describe the question rather than the product.
GENERIC = set("""what whats is the a an for on of my your you do does are rate rates apy apr interest
dividend yield annual percentage current currently today now right please tell me give can could
how much get earn pay pays paying with between and or to in at month months year years model
dupaco dupacos offer offers have account accounts loan loans balance standard purchase new
s i about at any their there they them which who also like would want know need looking
wondering tell show list all some much many kind kinds type types option options available
offered right latest aprs apys charge charges provide
if then than so but not no yes keep kept put get got gets do did done does doing be been being am
was were will would should could may might must shall it its this that these those here there
when where who whom whose why how what which while during before after above below up down out
over under again further once only own same too very just also each few more most other some such
any both all nor into onto through from by about against between among per via my mine we us our
ours he she him her his hers they them their theirs i me you your yours one ones thing things
""".split())
HEAD = re.compile(r"\b([a-z]+)(?:[\s-]+rate)?[\s-]+(?:loans?|mortgages?|accounts?|cards?|certificates?|lines? of credit)\b")
LISTING = re.compile(r"\b(offer|offers|options|all|types|kinds|list|cards|loans|accounts|certificates)\b", re.I)
AUDIENCE_WORDS = {"business", "roth", "traditional", "ira", "personal"}
VARIANTS = ("jumbo", "refinance", "variable", "heloc", "intro")
SUPERLATIVE = {"highest": "highest", "best": "highest", "top": "highest", "most": "highest", "max": "highest",
               "maximum": "highest", "lowest": "lowest", "cheapest": "lowest", "least": "lowest",
               "min": "lowest", "minimum": "lowest"}
VEHICLE = r"(?:car|auto|automobile|vehicle|truck|motorcycle|suv|sedan|pickup)s?"
NEW_VEHICLE = re.compile(rf"\b(?:brand[- ])?new (?:model[- ]year )?{VEHICLE}\b")
# A calendar date ("in May 2026", "as of 09/28/2026") is when, not a model year.
DATED = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:\d{1,2},?\s+)?(?:19|20)\d\d\b"
                   r"|\b\d{1,2}/\d{1,2}/(?:19|20)\d\d\b|\b(?:in|of|since|during)\s+(?:19|20)\d\d\b")
THOUSANDS = re.compile(r"\$?\s?(\d+(?:\.\d+)?)\s?k\b")


HOME_LOAN = re.compile(r"\b(?:home|house) loans?\b")   # a mortgage; not home equity / home improvement


def _stem(w: str) -> str:
    w = SYNONYMS.get(w, w)
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w


def words(text: str) -> list[str]:
    return [_stem(w) for w in WORD.findall(HOME_LOAN.sub("mortgage", text.lower()))]


@dataclass
class RateQuery:
    product: list
    term: Optional[int] = None
    year: Optional[int] = None
    amount: Optional[tuple] = None
    metric: Optional[str] = None
    audience: str = "personal"
    ira_kind: Optional[str] = None
    variants: frozenset = frozenset()
    superlative: Optional[str] = None      # highest | lowest
    asks_number: bool = False              # explicitly asks for a rate/APY/APR value
    modifiers: list = None                 # words right before a product noun
    listing: bool = False                  # 'what X do you offer' / plural 'rates for the cards'
    newest: bool = False                   # "a new car": the newest model-year band only


PHRASES = [(re.compile(r"\bshare (certificates?)\b"), r"\1"),          # credit-union word for a CD
           (re.compile(r"\bcertificates? of deposits?\b"), "certificate"),
           (re.compile(r"\bterm[- ]share\b"), "certificate"),
           (HOME_LOAN, "mortgage"),
           (re.compile(r"\bhsas?\b"), "health savings account"),
           (THOUSANDS, lambda m: f"${float(m.group(1)) * 1000:,.0f}")]     # "$15k" -> "$15,000"


def parse(question: str) -> Optional[RateQuery]:
    q = question.lower()
    for rx, rep in PHRASES:
        q = rx.sub(rep, q)
    by_term = bool(TERM_PRODUCT.search(q)) and term_months(q) is not None
    if not (RATE_INTENT.search(q) or by_term) or NOT_RATE.search(q):
        return None
    # Audience words are a separate filter (rule R4), not part of the product name.
    raw = [w for w in WORD.findall(q) if _stem(w) not in GENERIC and w not in GENERIC
           and (w not in AUDIENCE_WORDS or w == "personal") and w not in ("iras", "retirement")]
    rq = RateQuery(product=[_stem(w) for w in raw])
    rq.modifiers = [m.group(1) for m in HEAD.finditer(q)
                    if m.group(1) not in GENERIC and m.group(1) not in SUPERLATIVE]
    rq.listing = bool(LISTING.search(q)) or bool(re.search(r"\b(rates|apys|aprs)\b", q))
    rq.term = term_months(q)
    rq.asks_number = (by_term or bool(re.search(r"\b(rates?|apys?|aprs?|interest rates?|dividend rates?)\b", q))) \
        and not re.search(r"\b(any|which)\b", q)
    # A year next to a loan or a vehicle is a model year ("a 2026 Honda Civic for 60 months").
    if (m := re.search(r"\b(19[89]\d|20[0-3]\d)\b", DATED.sub(" ", q))) and \
            (rq.term or re.search(rf"\b(?:{VEHICLE}|model|loans?|financ\w*)\b", q)):
        rq.year = int(m.group(1))
        if "auto" not in rq.product and not re.search(r"\b(?:boat|rv|atv|snowmobile|home|mortgage)", q):
            rq.product.append("auto")
    rq.newest = not rq.year and bool(NEW_VEHICLE.search(q))
    if (m := MONEY_RANGE.search(q)) or (m := re.search(r"\$\s?(\d[\d,]*)\s*(?:and|-|to)\s*\$?\s?(\d[\d,]*)", q)):
        rq.amount = (float(m.group(1).replace(",", "")), float(m.group(2).replace(",", "")))
    elif (m := re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)", q)):
        v = float(m.group(1).replace(",", ""))
        rq.amount = (v, v)
    if "apy" in q or "annual percentage yield" in q or re.search(r"\byield", q):
        rq.metric = "apy"
    elif "apr" in q or "annual percentage rate" in q:
        rq.metric = "apr"
    elif "dividend rate" in q:
        rq.metric = "rate"
    if "business" in q:
        rq.audience = "business"
    elif re.search(r"\b(ira|iras|roth|traditional|retirement)\b", q):
        rq.audience = "ira"
        rq.ira_kind = "roth" if "roth" in q else ("traditional" if "traditional" in q else None)
    rq.variants = frozenset(v for v in VARIANTS if v in q or (v == "refinance" and "refi" in q)
                            or (v == "intro" and re.search(r"\bpromo|balance transfer", q)))
    rq.superlative = next((kind for w, kind in SUPERLATIVE.items() if re.search(rf"\b{w}\b", q)), None)
    return rq


def _fits(f: RateFact, rq: RateQuery) -> bool:
    """Hard constraints: an explicit qualifier in the question must not be contradicted."""
    if f.audience != rq.audience and not (rq.listing and rq.audience == "personal" and f.audience == "business"):
        return False
    if rq.ira_kind and f.ira_kind and f.ira_kind != rq.ira_kind:
        return False
    if rq.term and f.term and f.term != rq.term:
        return False
    if rq.year and f.years and not (f.years[0] <= rq.year <= f.years[1]):
        return False
    if rq.amount and f.amount:
        lo, hi = rq.amount
        if not (f.amount[0] - 1 <= lo and hi <= f.amount[1] + 1):
            return False
    for v in VARIANTS:
        if (v in rq.variants) != (v in f.flags):
            if v in rq.variants:
                return False
    return True


class RateBook:
    """All rate facts of one snapshot, plus IDF weights over their product words.
    `site_df(word)` gives the share of the snapshot's passages that use a word, which tells a
    product term ("construction", "adjustable") apart from filler ("was", "provide")."""

    def __init__(self, facts: list, site_df=None, withdrawn=()):
        self.facts = facts
        self.site_df = site_df or (lambda w: 0.0)
        df = Counter()
        self._words = []
        for f in facts:
            ws = set(words(f"{f.section} {f.name}"))
            self._words.append(ws)
            df.update(ws)
        n = max(1, len(facts))
        self.idf = {w: math.log(1 + n / c) for w, c in df.items()}
        # Words of ended or withdrawn offers stay product words, so a question about one finds
        # no current row and is declined rather than answered with the nearest live product.
        for f in withdrawn:
            for w in words(f"{f.section} {f.name}"):
                self.idf.setdefault(w, math.log(1 + n))
        vals = sorted(self.idf.values())
        self._unknown = vals[len(vals) // 2] if vals else 1.0

    def _query_words(self, rq) -> list:
        """Product words that must be matched: every word some rate table uses, plus any
        unknown word that directly modifies the product noun ("construction loan",
        "adjustable-rate mortgage"). That is a product the rate sheets don't list (rule R6).
        Other unknown words are filler ("provide", "was")."""
        out = [w for w in rq.product if w in self.idf]
        out += [_stem(w) for w in rq.modifiers if _stem(w) not in self.idf]
        return list(dict.fromkeys(out))

    def _w(self, w: str) -> float:
        return self.idf.get(w, self._unknown)

    def _product_score(self, qs: list, fwords: set) -> float:
        if not qs:
            return 0.0
        total = sum(self._w(w) for w in qs)
        return sum(self._w(w) for w in qs if w in fwords) / total

    def lookup(self, rq: RateQuery):
        """Return (winning facts from one page, all candidate facts) or (None, candidates)."""
        if rq.term:
            # A product priced by term (15/20/30-year mortgages) has no rate for a term it doesn't
            # list: a 10-year mortgage must not fall through to another product's 120-month row.
            _, product = self.lookup(replace(rq, term=None))
            if any(f.term for f in product) and not any(f.term == rq.term for f in product):
                return None, []
        scored = []
        qs = self._query_words(rq)
        for f, fw in zip(self.facts, self._words):
            if not _fits(f, rq):
                continue
            s = self._product_score(qs, fw)
            if rq.term and not f.term:
                s -= 0.3          # the question names a term; prefer products that have terms
            if s >= 0.5:
                scored.append((s, f))
        if not scored:
            return None, []
        # Score per product section (a table), so rows of one product stay together.
        by_sec = {}
        for s, f in scored:
            label = f.section.split(" / ")[-1].lower()
            extra = len([w for w in set(words(label)) if w not in GENERIC and w not in qs and w not in AUDIENCE_WORDS])
            k = (f.audience, label)
            by_sec[k] = max(by_sec.get(k, -1), s - 0.01 * extra)   # tightest product label wins ties
        best = max(by_sec.values())
        # Sections within a small margin compete on authority (R2); the extra-word tie-break
        # only chooses between sections of the winning page.
        keep = {k for k, s in by_sec.items() if s >= best - 0.05}
        top = [f for s, f in scored if (f.audience, f.section.split(" / ")[-1].lower()) in keep
               and s >= best - 0.005 - 0.01 * 9]
        # Prefer the plain product over variants the question did not ask for (jumbo, refinance…).
        for v in VARIANTS:
            if v == "jumbo" and rq.amount:
                continue                  # "jumbo" is a balance tier: the amount decides (_narrow)
            if v not in rq.variants and any(v not in f.flags for f in top):
                top = [f for f in top if v not in f.flags]
        # Rule R2 + R3: one page wins: highest authority, then newest printed date, then URL.
        def rank(f):
            return (not f.page.carried, f.page.tier, f.page.printed_date or "", f.page.key)
        win = max(top, key=rank)
        on_page = {(f.audience, f.section.split(" / ")[-1].lower()) for f in top if f.page is win.page}
        win_sec = max(on_page, key=lambda k: (by_sec[k], k))[1]
        if rq.listing:
            # One winning page per audience (personal first), every matching product on it.
            rows = []
            for aud in ("personal", "ira", "business"):
                group = [f for f in top if f.audience == aud]
                if group:
                    p = max(group, key=rank).page
                    secs = {(f.audience, f.section.split(" / ")[-1].lower()) for f in group if f.page is p}
                    best_here = max(by_sec[k] for k in secs)
                    rows += [f for f in group if f.page is p and
                             by_sec[(f.audience, f.section.split(" / ")[-1].lower())] >= best_here - 0.005]
        else:
            rows = [f for f in top if f.page is win.page and f.section.split(" / ")[-1].lower() == win_sec]
        rows = _narrow(rows, rq)
        if rq.superlative and rows:
            metric = rq.metric or ("apr" if rows[0].is_loan else "apy")
            vals = [(_pct(f.values.get(metric)), f) for f in rows if f.values.get(metric)]
            if vals:
                pick = (max if rq.superlative == "highest" else min)(vals, key=lambda x: x[0])
                rows = [pick[1]]
        return rows, top


def _narrow(rows: list, rq: RateQuery) -> list:
    """Keep only the tier that was asked for (rule R4)."""
    if rq.newest and any(f.years for f in rows):
        band = max((f.years for f in rows if f.years), key=lambda b: (b[1], b[0]))
        rows = [f for f in rows if f.years == band]
    if rq.amount:
        # Several bands can contain the amount: "$300,000 or less" and "$832,750 or less" for
        # $250,000, or a $1,000 minimum and a $100,000 jumbo minimum for $150,000. The tier is the
        # narrowest band, and among open-ended minimums the highest one reached.
        def tight(f):
            return (f.amount[1] - f.amount[0], -f.amount[0])
        best = {}
        for f in rows:
            if f.amount:
                k = (f.section, f.term, f.years)
                best[k] = min(best.get(k, (INF, 0)), tight(f))
        rows = [f for f in rows if not f.amount or tight(f) == best[(f.section, f.term, f.years)]]
    return rows


def _pct(s: Optional[str]) -> float:
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else -1.0


def _tier_words(f: RateFact) -> str:
    bits = [f.name] + [c for c in f.cells[1:] if re.search(r"\b(months?|years?)\b", c, re.I) and "%" not in c]
    if f.tier_label and f.tier_label not in bits:
        bits.append(f.tier_label)
    if f.amount and f.amount[1] == INF and f.amount[0] >= 1000 and "$" not in " ".join(bits):
        bits.append(f"${f.amount[0]:,.0f} minimum")
    return ", ".join(dict.fromkeys(b for b in bits if b))


def describe(f: RateFact, metric: Optional[str]) -> str:
    """'2024-27 Model Year, 60 Months: 5.39% APR'"""
    v = f.values
    if metric and metric in v:
        val = f"{v[metric]} {'dividend rate' if metric == 'rate' else metric.upper()}"
    elif "apy" in v:
        val = f"{v['apy']} APY" + (f" ({v['rate']} dividend rate)" if "rate" in v else "")
    elif "apr" in v:
        val = (f"{v['rate']} rate / " if "rate" in v else "") + f"{v['apr']} APR"
    else:
        val = f"{v.get('rate')} rate"
    return f"{_tier_words(f)}: {val}"


def compose(rows: list, rq: RateQuery) -> str:
    order = {"personal": 0, "ira": 1, "business": 2}
    rows = sorted(rows, key=lambda f: (order[f.audience], f.section, f.term or 0, f.years or (0, 0),
                                       f.amount or (0, 0), f.name))[:12 if rq.listing else 8]
    if len({f.section for f in rows}) > 1:
        return "; ".join(f"{f.section.split(' / ')[-1]} - {describe(f, rq.metric)}" for f in rows) + "."
    product = rows[0].section.split(" / ")[-1]
    lines = [describe(f, rq.metric) for f in rows]
    lines = [l[len(product) + 2:] if l.startswith(product + ": ") else l for l in lines]
    return f"{product}: " + "; ".join(lines) + "."
