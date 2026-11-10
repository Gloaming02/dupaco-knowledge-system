"""Fees as structured facts, the same way rates are (docs/RULES.md, R4 and R6).

A fee is a (label, amount) pair on a page: "Domestic wire | $25.00 each". Fee questions are
answered from these pairs, never from a passage that merely mentions the word "fee", so the
amount in the answer always belongs to the fee that was asked about.

Three layouts carry fees on a credit-union site:
  * a fee-schedule table        |Stop payment (check, ACH, & bill pay)|$30.00* per item|
  * a fee schedule as text      Stop payment (check, ACH, & bill pay) $30.00* per item
  * a disclosure sentence       Other fees include: cash advance fee—$10.00 or 3.00% of …; late payment fee is …
"""
import html
import math
import re
from collections import Counter
from dataclasses import dataclass

from . import authority
from .text import STOP, iter_blocks
from .urls import path_of

INTENT = re.compile(r"\bfees?\b|\bcharges?\b|\bcosts?\b|\bhow much (?:is|are|does|do|for|to|would)\b", re.I)
# What a fee amount looks like at the start of a cell or after a label.
AMOUNT = re.compile(r"\$\s?\d|\bfree\b|\d+(?:\.\d+)?\s?%|\bno charge\b|\bprice varies\b", re.I)
SCHEDULE = re.compile(r"fee schedule|fees and charges|service charges", re.I)
TEXT_ROW = re.compile(r"^(?P<label>[A-Za-z][^$|\n]{2,110}?)\s+(?P<amount>(?:\$\s?\d|Free\b|\d+(?:\.\d+)?\s?%|Price varies|Available at no charge)[^\n]*)$")
DISCLOSURE = re.compile(r"fees include:\s*(?P<items>[^\n]{10,700})", re.I)
DISCLOSED = re.compile(r"^\s*(?:and\s+)?(?P<label>[A-Za-z][A-Za-z ]{2,40}?\bfee)\s*(?:[—–-]|:|\bis\b)\s*(?P<amount>.+)$", re.I)
WORD = re.compile(r"[a-z]+")


def tokens(text: str) -> list:
    """Whole words with plurals folded ("overdrafts" = "overdraft"). Deliberately stricter than
    the search tokenizer, whose prefix stemming would merge "certificate" with "certified draft"."""
    out = []
    for w in WORD.findall(text.lower()):
        if w in STOP:
            continue
        out.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


# Words of the question that say "this is a fee question" rather than which fee.
FILLER = set(tokens("fee fees charge charges cost costs much there any pay paid price amount"))


@dataclass
class FeeFact:
    page: object
    label: str            # "Domestic wire"
    amount: str           # "$25.00 each"
    section: str          # "Teller and Cash Handling Service Charges"
    business: bool = False

    @property
    def text(self) -> str:
        return f"{self.label}: {self.amount}"


def _clean(s: str) -> str:
    s = html.unescape(html.unescape(s)).replace("\\*", "*").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip(" *")


def _amount(s: str) -> str:
    return re.sub(r"\s*\*\s*", " ", _clean(s)).strip(" -–—")


def _value(amount: str):
    """The first figure of an amount, so "$15" and "$15.00 or the minimum due" compare equal."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", amount)
    return float(m.group().replace(",", "")) if m else amount.lower()


def _fact(page, label, amount, section) -> FeeFact:
    business = bool(re.search(r"\bbusiness\b", f"{section} {label}", re.I)) or path_of(page.url).startswith("/business")
    return FeeFact(page=page, label=_clean(label), amount=_amount(amount), section=_clean(section), business=business)


def _table_rows(page) -> list:
    """Rows of a fee-schedule table. A row with a label and no amount is a sub-heading
    ("Debit Card Service Charges"); a "header" row that carries an amount is really a data row
    (the PDF-to-markdown step promotes the first row of each table to a header)."""
    out, section, seen_headers = [], "", set()
    for b in iter_blocks(page.markdown, page.title):
        if b[0] != "row":
            continue
        _, heading, _label, header, cells = b
        if id(header) not in seen_headers:
            seen_headers.add(id(header))
            if len(header) > 1 and AMOUNT.match(header[1]):
                out.append(_fact(page, header[0], header[1], section or heading))
            elif header and not re.fullmatch(r"col\d+", header[0], re.I):
                section = header[0]
        label, rest = cells[0], [c for c in cells[1:] if c]
        if not label:
            continue
        if not rest:
            if len(label) < 80:
                section = label
            continue
        if AMOUNT.match(rest[0]) and "%" not in label and _is_label(label):
            out.append(_fact(page, label, rest[0], section or heading))
    return out


def _is_label(label: str) -> bool:
    """A fee name, not a sentence that happens to end in an amount."""
    return len(label.split()) <= 12 and ". " not in label


def _text_rows(page) -> list:
    """The same schedule when it was captured as plain lines instead of a table. A short line
    without an amount is a sub-heading ("Debit Card Service Charges"), unless the next line
    continues it ("Foreign currency exchange fee" / "(includes Canadian checks) $35.00")."""
    out, section, pending = [], "", ""
    for raw in page.markdown.splitlines():
        line = _clean(raw)
        if not line or line.startswith("|") or line.startswith("#"):
            pending = ""
            continue
        continues = bool(pending) and (line[0] == "(" or line[0].islower())
        if pending and not continues and pending[0].isupper():
            section = pending                                   # the held line was a sub-heading
        m = TEXT_ROW.match(f"{pending} {line}" if continues else line)
        if m and _is_label(m.group("label")):
            out.append(_fact(page, m.group("label"), m.group("amount"), section))
            pending = ""
        elif not m and "$" not in line and len(line) < 70 and not line.endswith("."):
            pending = line
        else:
            pending = ""
    return out


def _disclosed(page) -> list:
    out = []
    for m in DISCLOSURE.finditer(page.markdown):
        for item in m.group("items").split(";"):
            item = re.split(r"\.\s+(?=[A-Z\[])|\._?$", item)[0]          # stop at the end of the sentence
            if (d := DISCLOSED.match(item)):
                out.append(_fact(page, d.group("label"), d.group("amount"), page.title.split("|")[0]))
    return out


def extract(page) -> list:
    if page.tier <= authority.EDITORIAL:
        return []                                   # a blog quoting an old fee is not the fee schedule
    out = _disclosed(page)
    if SCHEDULE.search(f"{page.url} {page.title} {page.markdown[:1500]}"):
        out += _table_rows(page) or _text_rows(page)
    seen, uniq = set(), []
    for f in out:
        k = (f.label.lower(), f.amount.lower())
        if f.label and f.amount and k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


AUDIENCE = set(tokens("consumer consumers business personal member members"))


def _key_tokens(label: str) -> set:
    """The words that name the fee: no bracketed remarks, sizes or audience words."""
    core = re.sub(r"\([^)]*\)", " ", label)
    return {t for t in tokens(core) if len(t) > 1} - FILLER - AUDIENCE


class FeeBook:
    """All fee facts of one snapshot."""

    def __init__(self, view):
        self.facts = [f for p in sorted(view.pages.values(), key=lambda p: p.key) if not p.expired
                      for f in extract(p)]
        self._label = [_key_tokens(f.label) for f in self.facts]
        self._context = [set(tokens(f"{f.section} {f.page.title} {path_of(f.page.url).replace('/', ' ').replace('-', ' ')}"))
                         for f in self.facts]
        df = Counter(t for ts in self._label for t in ts)
        n = max(1, len(self.facts))
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
        vals = sorted(self.idf.values())
        self._filler = vals[0] if vals else 1.0     # a word no fee label uses is treated as filler
        # A page that prints two amounts under one label (two cards' footnotes) can't say which.
        amounts = {}
        for f in self.facts:
            amounts.setdefault((f.page.key, f.label.lower()), set()).add(f.amount.lower())
        self._ambiguous = {k for k, v in amounts.items() if len(v) > 1}

    def _w(self, toks) -> float:
        return sum(self.idf.get(t, self._filler) for t in toks)

    def lookup(self, question: str) -> list:
        """The fee rows that answer the question: the row whose label was asked for, or the
        rows of one family when the question names the family but not the member ("wire":
        incoming, domestic, international). Empty when no fee label is named: a row that only
        shares a word with the question ("Merchant Visa processing fees" for a Visa annual fee)
        is not an answer."""
        q = set(tokens(question)) - FILLER
        if not q or not self.facts:
            return []
        want_business = bool(re.search(r"\bbusiness\b", question, re.I))
        scored = []                                     # (question cover, label cover, fact, matched words)
        for f, label, ctx in zip(self.facts, self._label, self._context):
            hit = q & label
            if not hit or f.business != want_business:
                continue
            scored.append((self._w(q & (label | ctx)) / self._w(q), self._w(hit) / self._w(label), f, hit))
        # The gate is the label: the question must name at least half of it (by weight). Other
        # words of the question ("on the Platinum Visa") only choose between pages.
        named = [x for x in scored if x[1] >= 0.5]
        if not named:
            return []
        q_top, l_top, top, top_hit = max(named, key=lambda x: (round(x[1], 2), x[0], x[2].page.tier, x[2].page.key))
        tied = {x[2].label.lower() for x in named if round(x[1], 2) == round(l_top, 2)}
        if l_top < 0.999 and len(tied) == 1:
            family = [x for x in named if x[2].label.lower() in tied]      # one row is clearly meant
        elif l_top < 0.999:
            # The family was asked for, not one member ("wire": incoming, domestic, international).
            # Its name is the matched word most labels share, as long as that is a short list.
            shared = {t: sum(t in label for label in self._label) for t in top_hit}
            small = [t for t in top_hit if shared[t] <= 8]
            key = max(small, key=lambda t: (shared[t], t)) if small else min(top_hit, key=lambda t: (shared[t], t))
            family = [x for x in scored if key in x[3]]
        else:
            family = [x for x in named if x[1] >= 0.999 and x[3] >= top_hit]
        # One row per label: the best-matching context, then a page that is unambiguous about
        # the amount, then the most authoritative, newest-dated page (R2, R3).
        by_label = {}
        for qc, lc, f, _ in family:
            k = f.label.lower()
            rank = (round(qc, 1), (f.page.key, k) not in self._ambiguous, not f.page.carried,
                    f.page.tier, f.page.printed_date or "", f.page.key)
            if k not in by_label or rank > by_label[k][0]:
                by_label[k] = (rank, f)
        order = {id(f): i for i, f in enumerate(self.facts)}
        return sorted((f for _, f in by_label.values()), key=lambda f: order[id(f)])[:6]

    def other_amounts(self, fact) -> list:
        """Amounts other pages print for the same fee (for the conflict note)."""
        return sorted({f.amount for f in self.facts if f.label.lower() == fact.label.lower()
                       and f.business == fact.business and _value(f.amount) != _value(fact.amount)})
