"""Structured rate facts from table rows (docs/RULES.md, rule R4).

A table row with a percentage becomes a RateFact carrying its full *fact key*: product,
audience, term, model-year band, amount tier, variant flags. It also carries one value per
metric (dividend rate / APY / APR). Cell contents beat headers when they disagree (the
vehicle-affordability calculator labels an APR column "Annual Percentage Yield").
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from .text import iter_blocks, row_text

INF = float("inf")
PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
TERM = re.compile(r"\b(\d{1,3})[\s-]*(months?|mos?\b|years?|yrs?\b)", re.I)
YEARS = re.compile(r"\b((?:19|20)\d\d)\s*[-–]\s*((?:19|20)?\d\d)\b")
ONE_YEAR_OLDER = re.compile(r"\b((?:19|20)\d\d)\s+model year\s*\(and older\)", re.I)
MONEY = r"\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
MONEY_RANGE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(?:[-–]|to)\s*\$?\s?(\d[\d,]*(?:\.\d+)?)")
MONEY_ONE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(\+|or less|or more|and up)?", re.I)
LOAN_WORDS = re.compile(r"loan|mortgage|apr|visa|card|heloc|equity|line of credit|refinance", re.I)
FOOTNOTE = re.compile(r"%\d+")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def term_months(text: str) -> Optional[int]:
    m = TERM.search(text)
    if not m:
        return None
    n = int(m.group(1))
    return n * 12 if m.group(2).lower().startswith("y") else n


def year_band(text: str):
    if (m := ONE_YEAR_OLDER.search(text)):
        return (1900, int(m.group(1)))
    if (m := YEARS.search(text)) and "model" in text.lower():
        a, b = m.group(1), m.group(2)
        b = int(a[:2] + b) if len(b) == 2 else int(b)
        a = int(a)
        return (min(a, b), max(a, b))
    return None


def amount_band(text: str):
    if (m := MONEY_RANGE.search(text)):
        return (_num(m.group(1)), _num(m.group(2)))
    if (m := MONEY_ONE.search(text)):
        v, tail = _num(m.group(1)), (m.group(2) or "").lower()
        if tail == "or less":
            return (0.0, v)
        if tail in ("+", "or more", "and up"):
            return (v, INF)
    return None


@dataclass
class RateFact:
    page: object                       # PageVersion
    section: str                       # "Rates / Auto & Motorcycle Loans"
    name: str                          # first cell: "2024-27 Model Year", "Share Savings"…
    text: str                          # the whole row as text
    cells: list
    audience: str = "personal"         # personal | business | ira
    ira_kind: Optional[str] = None     # roth | traditional
    is_loan: bool = False
    term: Optional[int] = None         # months
    years: Optional[tuple] = None      # model-year band
    amount: Optional[tuple] = None     # balance / loan-amount band
    flags: frozenset = frozenset()     # jumbo, special, refinance, variable, …
    tier_label: str = ""                # the cell that defines the balance/amount tier, as printed
    values: dict = field(default_factory=dict)   # metric -> display string ("5.39%", "12.50% – 19.50%")

    @property
    def product_text(self) -> str:
        return f"{self.section} {self.name} {self.page.title}"

    def key(self) -> tuple:
        """Identity without the value, used to decide what is a conflict (rule R4)."""
        prod = re.sub(r"[^a-z ]", " ", f"{self.section.split('/')[-1]} {self.name}".lower())
        prod = " ".join(w for w in prod.split() if w not in {"rates", "rate", "month", "months", "year", "model"})
        return (self.audience, self.ira_kind, prod, self.term, self.years, self.amount, self.flags)


def _metric(header: str, cell: str, is_loan: bool) -> str:
    c, h = cell.lower(), header.lower()
    if "apr" in c or "annual percentage rate" in c:
        return "apr"
    if "apy" in c:
        return "apy"
    if "apr" in h or "annual percentage rate" in h:
        return "apr"
    if "apy" in h or "annual percentage yield" in h:
        return "apy"
    if "dividend" in h or h.strip() in ("rate", "interest rate"):
        return "rate"
    return "apr" if is_loan else "apy"


def _display(cell: str) -> str:
    cell = FOOTNOTE.sub("%", cell)
    vals = PCT.findall(cell)
    return " – ".join(f"{v}%" for v in vals[:2])


def extract(page) -> list[RateFact]:
    out = []
    for b in iter_blocks(page.markdown, page.title):
        if b[0] != "row":
            continue
        _, heading, label, header, cells = b
        if not any(PCT.search(c) for c in cells):
            continue
        header = list(header) + [""] * (len(cells) - len(header))
        section = " / ".join(x for x in (heading, label) if x)
        name = cells[0]
        whole = f"{section} {' '.join(cells)} {page.url}".lower()
        is_loan = bool(LOAN_WORDS.search(f"{section} {name} {' '.join(header)}"))
        f = RateFact(page=page, section=section, name=name, cells=cells, is_loan=is_loan,
                     text=row_text(heading, label, header, cells))
        if "business" in f"{section} {name}".lower() or "/business" in page.url:
            f.audience = "business"
        if re.search(r"\bira", section.lower()) or re.match(r"(roth|traditional)\b", name.lower()):
            f.audience = "ira"
            f.ira_kind = "roth" if name.lower().startswith("roth") else (
                "traditional" if name.lower().startswith("traditional") else None)
        f.flags = frozenset(w for w in ("jumbo", "special", "refinance", "variable", "fixed", "heloc")
                            if w in whole.split("http")[0])
        for h, c in zip(header, cells):
            hl = h.lower()
            if PCT.search(c) and "payment" not in hl:
                f.values.setdefault(_metric(h, c, is_loan), _display(c))
                continue
            if "payment" in hl or "min. to open" in hl or "points" in hl:
                continue
            f.term = f.term or term_months(c)
            f.years = f.years or year_band(c)
            if f.amount is None and (band := amount_band(c)):
                f.amount = band
                if c != name:
                    f.tier_label = c
            elif f.amount is None and "min" in hl and (m := MONEY_ONE.search(c)):
                f.amount = (_num(m.group(1)), INF)
        if f.values:
            out.append(f)
    return out
