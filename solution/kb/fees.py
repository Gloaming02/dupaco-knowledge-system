"""Fees as structured facts, the same way rates are (docs/RULES.md, R4 and R6).

A fee is a (label, amount) pair on a page: "Domestic wire | $25.00 each". A fee question is
answered from one of these pairs or declined; it never falls back to a passage that merely
mentions the word "fee". Matching is by the words of the label, so it finds a fee only when
the question uses the schedule's own words (or a listed synonym): "sending money abroad" is
not recognised as an international wire and is declined.

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
# Words of rate-table rows that are not product names.
NOT_PRODUCTS = ("standard", "regular", "special", "fixed", "program", "rate", "type", "transfer", "balance",
                "introductory", "tier", "minimum", "month", "year", "model")
SCHEDULE = re.compile(r"fee schedule|fees and charges|service charges", re.I)
TEXT_ROW = re.compile(r"^(?P<label>[A-Za-z][^$|\n]{2,110}?)\s+(?P<amount>(?:\$\s?\d|Free\b|\d+(?:\.\d+)?\s?%|Price varies|Available at no charge)[^\n]*)$")
DISCLOSURE = re.compile(r"fees include:\s*(?P<items>[^\n]{10,700})", re.I)
DISCLOSED = re.compile(r"^\s*(?:and\s+)?(?P<label>[A-Za-z][A-Za-z ]{2,40}?\bfee)\s*(?:[—–-]|:|\bis\b)\s*(?P<amount>.+)$", re.I)
WORD = re.compile(r"[a-z]+|\d+")
# The schedule's vocabulary for the same thing said differently.
SYNONYMS = {"abroad": "international", "overseas": "international", "internationally": "international",
            "domestically": "domestic", "cashier": "official", "cashiers": "official", "nsf": "overdraft"}
SYNONYM_PHRASES = [(re.compile(r"\bwithin the (?:us|u\.s\.|united states|country)\b"), "domestic")]


def _stem(w: str) -> str:
    """drilling -> drill, closed/close -> clos, wires/wire -> wir. Lighter than the search
    tokenizer, whose six-letter prefixes would merge "certificate" with "certified draft"."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix) and not w.endswith("ss"):
            w = w[:-len(suffix)]
            break
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


def tokens(text: str) -> list:
    text = text.lower()
    for rx, word in SYNONYM_PHRASES:
        text = rx.sub(word, text)
    out = []
    for w in WORD.findall(text):
        w = SYNONYMS.get(w, w)
        if w in STOP or (len(w) == 1 and w.isalpha()):
            continue
        out.append(w if w.isdigit() else _stem(w))
    return out


# Words of the question that say "this is a fee question" rather than which fee.
FILLER = set(tokens("fee fees charge charges cost costs much there any pay paid price amount per each"))
AUDIENCE = set(tokens("consumer consumers business personal member members"))


@dataclass
class FeeFact:
    page: object
    label: str            # "Domestic wire"
    amount: str           # "$25.00 each"
    section: str          # "Teller and Cash Handling Service Charges"
    business: bool = False
    context: str = ""     # the paragraph a disclosure came from: it names the card it is about

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


def _fact(page, label, amount, section, context="") -> FeeFact:
    business = bool(re.search(r"\bbusiness\b", f"{section} {label}", re.I)) or path_of(page.url).startswith("/business")
    return FeeFact(page=page, label=_clean(label), amount=_amount(amount), section=_clean(section),
                   business=business, context=context)


def _is_label(label: str) -> bool:
    """A fee name, not a sentence that happens to end in an amount."""
    return len(re.sub(r"\([^)]*\)", " ", label).split()) <= 12 and ". " not in label


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


NO_FEE = re.compile(r"\b(?:there (?:is|are) )?no ((?:[a-z]+ ){1,2}fees?)((?: (?:and|or|,) (?:no )?(?:[a-z]+ ){1,2}fees?)*)", re.I)


def _disclosed(page) -> list:
    """Fees a card disclosure states in a sentence, including the ones it says do not exist
    ("There is no annual fee and no balance transfer fee"). The paragraph is kept as context:
    it is what says which card the sentence is about."""
    out = []
    for m in DISCLOSURE.finditer(page.markdown):
        start = page.markdown.rfind("\n", 0, m.start()) + 1
        end = page.markdown.find("\n", m.end())
        para = _clean(page.markdown[start:end if end != -1 else None])
        for item in m.group("items").split(";"):
            item = re.split(r"\.\s+(?=[A-Z\[])|\._?$", item)[0]          # stop at the end of the sentence
            if (d := DISCLOSED.match(item)):
                out.append(_fact(page, d.group("label"), d.group("amount"), page.title.split("|")[0], para))
        for n in NO_FEE.finditer(para):
            said = _clean(n.group(0))
            for label in re.findall(r"((?:[a-z]+ ){1,2}fee)s?\b", n.group(0).lower()):
                label = re.sub(r"^(?:no|and|or|is|are) ", "", label.strip())
                out.append(_fact(page, label, f"none (the page says “{said}”)", page.title.split("|")[0], para))
    return out


def extract(page) -> list:
    if page.tier <= authority.EDITORIAL:
        return []                                   # a blog quoting an old fee is not the fee schedule
    out = _disclosed(page)
    if SCHEDULE.search(f"{page.url} {page.title} {page.markdown[:1500]}"):
        out += _table_rows(page) or _text_rows(page)
    seen, uniq = set(), []
    for f in out:
        k = (f.label.lower(), f.amount.lower(), f.context)
        if f.label and f.amount and k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def _core(label: str) -> set:
    """The words that name the fee: no bracketed remarks, no audience words."""
    return set(tokens(re.sub(r"\([^)]*\)", " ", label))) - FILLER - AUDIENCE


class FeeBook:
    """All fee facts of one snapshot.

    `product_of(word)` names the priced product a word refers to (auto, mortgage, platinum…)
    or returns None. A fee is not attributed to a product its own page never mentions: the
    card disclosure's late payment fee is not "the late fee on my auto loan"."""

    def __init__(self, view, product_of=None):
        self.facts = [f for p in sorted(view.pages.values(), key=lambda p: p.key) if not p.expired
                      for f in extract(p)]
        self.product_of = product_of or (lambda word: None)
        self._core = [_core(f.label) for f in self.facts]
        self._all = [set(tokens(f.label)) - FILLER - AUDIENCE for f in self.facts]
        where = [f"{f.label} {f.section} {f.context} {f.page.title} {path_of(f.page.url).replace('/', ' ').replace('-', ' ')}"
                 for f in self.facts]
        self._where = [set(tokens(w)) for w in where]
        # The fee vocabulary is the words that name fees; a verb inside a bracketed remark
        # ("send check") does not make "sending" a fee word.
        self.vocab = set().union(*self._core) if self._core else set()
        self._products = [self._product_words(w) for w in where]
        df = Counter(t for ts in {f.label.lower(): ts for f, ts in zip(self.facts, self._all)}.values() for t in ts)
        n = max(1, len({f.label.lower() for f in self.facts}))
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
        # A page that prints two amounts under one label (two cards' footnotes) can't say which.
        amounts = {}
        for f in self.facts:
            amounts.setdefault((f.page.key, f.label.lower()), set()).add(_value(f.amount))
        self._ambiguous = {k for k, v in amounts.items() if len(v) > 1}

    def _product_words(self, text: str, skip_fee_words: bool = False) -> set:
        out = set()
        for w in re.findall(r"[a-z]+", text.lower()):
            if skip_fee_words and tokens(w) and tokens(w)[0] in self.vocab:
                continue                                # a word of the fee's own name, not a product
            if (p := self.product_of(w)):
                out.add(p)
        return out

    def _w(self, toks) -> float:
        return sum(self.idf.get(t, 1.0) for t in toks)

    def lookup(self, question: str) -> list:
        """The fee rows that answer the question, or [] when none can be named with confidence.

        Only the question's fee words count (words some fee label uses); the rest is phrasing.
        Two measures per row: how much of the question's fee words the row explains (by its
        label, or by the card its paragraph is about), and how much of the row's label the
        question says.

        A row that explains every fee word answers, if the question also says at least half of
        its label ("drilling a safe deposit box" -> "Drill box open"). When several rows do,
        the ones named in full win (the "safe deposit box" sizes); otherwise the family is
        listed when it is short ("ATM": own ATMs free, others $0.50; "wire transfer": incoming,
        domestic, international).

        A row that leaves a fee word unexplained is not an answer, however close it looks:
        "returned check" is not the card's "returned payment fee". And a row is never used for
        a product its page does not mention."""
        words = set(tokens(question)) - FILLER
        q = words & self.vocab
        if not q or not self.facts:
            return []
        want_business = bool(re.search(r"\bbusiness\b", question, re.I))
        asked_products = self._product_words(question, skip_fee_words=True)
        label_of = lambda c: self.facts[c[4]].label.lower()
        cands = []                       # (question cover, label cover, label alone explains it, context hits, index)
        for i, f in enumerate(self.facts):
            if not q & self._all[i] or f.business != want_business or not asked_products <= self._products[i]:
                continue
            core = self._core[i]
            explained = q & (self._all[i] | self._where[i])
            cands.append((self._w(explained) / self._w(q), self._w(q & core) / max(self._w(core), 1e-9),
                          explained <= core, len((words - q) & self._where[i]), i))
        chosen = []
        full = [c for c in cands if c[0] >= 0.999]
        if full:
            if any(c[2] for c in full):
                full = [c for c in full if c[2]]         # named by the label itself, not a remark or the context
            exact = [c for c in full if c[1] >= 0.999]
            if exact:
                chosen = exact
            elif len({label_of(c) for c in full}) == 1:
                chosen = full if full[0][1] >= 0.5 else []
            else:
                # A family is rows of one document: the schedule's wires, not also a card's
                # "balance transfer fee" because it shares the word "transfer".
                pages = {self.facts[c[4]].page.key for c in full}
                family = [c for c in cands if q & self._core[c[4]] and self.facts[c[4]].page.key in pages]
                chosen = family if len({label_of(c) for c in family}) <= 4 else full
        # One row per label: the page whose context matches the question best, then one that
        # is unambiguous about the amount, then the most authoritative, newest-dated (R2, R3).
        by_label = {}
        for _, _, _, ctx, i in chosen:
            f = self.facts[i]
            k = f.label.lower()
            rank = (ctx, (f.page.key, k) not in self._ambiguous, not f.page.carried,
                    f.page.tier, f.page.printed_date or "", f.page.key)
            if k not in by_label or rank > by_label[k][0]:
                by_label[k] = (rank, i)
        return [self.facts[i] for i in sorted(i for _, i in by_label.values())][:6]

    def other_amounts(self, fact) -> list:
        """Amounts other pages print for the same fee (for the conflict note)."""
        return sorted({f.amount for f in self.facts if f.label.lower() == fact.label.lower()
                       and f.business == fact.business and _value(f.amount) != _value(fact.amount)})
