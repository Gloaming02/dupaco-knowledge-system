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
PRODUCT_NOUN = re.compile(r"certificate|\bcds?\b|savings|checking|money market|\bira|loan|visa|card|mortgage|club", re.I)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
NUMBER_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
                     "twenty-four": 24, "thirty-six": 36, "forty-eight": 48, "seventy-two": 72,
                     "eighty-four": 84, "eighteen": 18})
_NUMW = re.compile(r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")(?=[\s-]+(?:months?|years?|yrs?|mos?)\b)", re.I)


def term_months(text: str) -> Optional[int]:
    text = _NUMW.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), text)
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
    extras: dict = field(default_factory=dict)   # other printed columns: min_open, min_earn

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


PROSE = re.compile(r"^\s*[-*]?\s*(?P<label>[A-Za-z0-9][^:%\n]{3,80}?)\s*(?::|\b(?:is|of|at)\b|(?=\b(?:APY|APR)\b))\s*"
                   r"(?:(?P<metric>APY|APR|dividend rate|rate)\s*:?\s*)?(?P<value>\d{1,2}(?:\.\d{1,3})?\s*%)"
                   r"(?P<rest>[^\n]{0,80})$", re.I | re.M)


def _prose_facts(page) -> list:
    """Short 'label: 3.50%' lines outside tables. Only on non-editorial pages: blog prose
    is full of incidental percentages."""
    from . import authority
    if page.tier <= authority.EDITORIAL:
        return []
    out, heading = [], page.title
    for line in page.markdown.splitlines():
        if line.lstrip().startswith("#"):
            heading = line.lstrip("# ").strip()
            continue
        if line.lstrip().startswith("|") or len(line) > 200:
            continue
        m = PROSE.match(line)
        if not m:
            continue
        label = m.group("label").strip(" -*")
        if re.search(r"\bfees?\b", label, re.I):
            continue
        metric_word = (m.group("metric") or "") + " " + label
        is_loan = bool(LOAN_WORDS.search(f"{heading} {label}"))
        f = RateFact(page=page, section=heading, name=label, cells=[label, m.group("value")], is_loan=is_loan,
                     text=f"{heading}: {line.strip()}")
        f.values[_metric(metric_word, m.group("value") + " " + (m.group("metric") or ""), is_loan)] = _display(m.group("value"))
        f.term = term_months(label)
        f.years = year_band(label)
        f.amount = amount_band(label + " " + (m.group("rest") or ""))
        low = f"{heading} {label}".lower()
        f.flags = frozenset(w for w in ("jumbo", "special", "refinance", "variable", "fixed", "heloc") if w in low)
        if re.search(r"\bbusiness\b", low) or "/business" in page.url:
            f.audience = "business"
        out.append(f)
    return out


def extract(page) -> list[RateFact]:
    out = _prose_facts(page)
    for b in iter_blocks(page.markdown, page.title):
        if b[0] != "row":
            continue
        _, heading, label, header, cells = b
        if not any(PCT.search(c) for c in cells) or re.search(r"\bfees?\b", cells[0], re.I):
            continue                                   # a percentage fee row is not a rate
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
        if re.search(r"introductory|intro\b|promo|balance transfer", name, re.I):
            f.flags = f.flags | {"intro"}
        max_balance = None
        for h, c in zip(header, cells):
            hl = h.lower()
            # Not rate columns. Mortgage "Points" cells read "0.00%" and would be taken for the APR.
            if "min. to open" in hl or "minimum to open" in hl:
                f.extras["min_open"] = c
                continue
            if "max" in hl and "%" not in c and (m := MONEY_ONE.search(c)):
                max_balance = _num(m.group(1))       # "Max. Balance $1,000": the tier ends there
                continue
            if "payment" in hl or "points" in hl:
                continue
            if PCT.search(c):
                f.values.setdefault(_metric(h, c, is_loan), _display(c))
                continue
            f.term = f.term or term_months(c)
            f.years = f.years or year_band(c)
            if f.amount is None and (band := amount_band(c)):
                f.amount = band
                if c != name:
                    f.tier_label = c
            elif f.amount is None and "min" in hl and (m := MONEY_ONE.search(c)):
                f.amount = (_num(m.group(1)), INF)
                f.extras["min_earn"] = c
        if max_balance is not None and (f.amount is None or f.amount[1] == INF):
            f.amount = (f.amount[0] if f.amount else 0.0, max_balance)
        if f.values:
            # A deposit row priced by term ("60 Month" under a bare "Regular" caption) is a
            # certificate even when the table never says so (older snapshots of /rates).
            if (not f.is_loan and f.term
                    and not re.search(r"certificate|\bcds?\b|savings|checking|money market|club", f"{f.section} {f.name}", re.I)):
                f.section = f"{f.section} Certificates"
            out.append(f)
    return out
