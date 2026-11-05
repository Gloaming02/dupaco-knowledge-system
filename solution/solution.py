"""
Knowledge system for the interface.ai build assignment.

    build() -> KnowledgeSystem with ingest(snapshot), answer(question, as_of), conflicts()

The rules behind every decision are in docs/RULES.md. Layout:
    kb/store.py      every version of every page, plus snapshot-by-date lookup (R1)
    kb/authority.py  page trust tiers from the URL (R2)
    kb/dates.py      dates printed on the page (R3)
    kb/index.py      BM25 per snapshot, re-ranked by authority
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
_harness = next((d / "harness" for d in _HERE.parents if (d / "harness" / "contract.py").exists()), None)
if _harness:
    sys.path.insert(0, str(_harness))
from contract import Answer, Conflict, Snapshot, Source  # noqa: E402

import re  # noqa: E402

from kb import directory, rates  # noqa: E402
from kb.links import INTENT as LINK_INTENT, LinkBook  # noqa: E402
from kb.conflicts import find as find_conflicts  # noqa: E402
from kb.index import SnapshotIndex  # noqa: E402
from kb.store import Store  # noqa: E402

REFUSAL = ("I'm not able to confirm that from Dupaco's website, so I don't want to guess. "
           "Please contact Dupaco or visit a branch for the current details.")


class KnowledgeSystem:
    def __init__(self):
        self.store = Store()
        self.indexes = {}          # snapshot_id -> SnapshotIndex
        self.ratebooks = {}        # snapshot_id -> RateBook
        self.linkbooks = {}        # snapshot_id -> LinkBook
        self._cache = {}           # (snapshot_id, question) -> Answer: same question, same answer (R8)
        self._stats_cache = {}
        self._conflicts = None
        self._tokens = {}          # chunk text -> token counts, shared across snapshots

    # -- contract ---------------------------------------------------------------------------
    def ingest(self, snapshot: Snapshot) -> None:
        view = self.store.add(snapshot)
        self._conflicts = None
        self.indexes[view.snapshot_id] = SnapshotIndex(view, self._tokens)
        self.ratebooks[view.snapshot_id] = rates.RateBook(
            [f for p in sorted(view.pages.values(), key=lambda p: p.key) for f in p.facts],
            site_df=self.indexes[view.snapshot_id].df)
        self.linkbooks[view.snapshot_id] = LinkBook(view)

    def answer(self, question, as_of=None):
        view = self.store.at(as_of)
        key = (view.snapshot_id, " ".join(question.lower().split()))
        if key not in self._cache:
            self._cache[key] = self._answer(question, view)
        return self._cache[key]

    def _answer(self, question, view):
        for route in (self._link, self._hours, self._address, self._branch_in, self._phone, self._stats):
            try:
                a = route(question, view)
            except Exception:          # a specialised route must never sink the whole answer
                a = None
            if a is not None:
                return a
        rq = rates.parse(question)
        if rq:
            rows, candidates = self.ratebooks[view.snapshot_id].lookup(rq)
            if rows:
                page = rows[0].page
                others = sorted({v for f in candidates if f.page is not page for v in f.values.values()}
                                - {v for f in rows for v in f.values.values()})
                note = (f"Other pages show {', '.join(others)}; using the {page.url} "
                        f"({rates.authority_name(page.tier)}) as the authoritative source.") if others else None
                return Answer(text=rates.compose(rows, rq),
                              sources=[Source(url=page.url, snapshot_id=page.snapshot_id, quote=rows[0].text[:200])],
                              conflict_note=note)
            if rq.asks_number:
                # A rate question no current rate table answers: don't guess from blog text (R6).
                return Answer(text=REFUSAL, confident=False)
        if (missing := self._unknown_entity(question, view)):
            return Answer(text=REFUSAL, confident=False,
                          conflict_note=f"'{missing}' does not appear anywhere on the site in {view.snapshot_id}.")
        hits = self.indexes[view.snapshot_id].search(question, k=40)
        if not hits:
            return Answer(text=REFUSAL, confident=False)
        top, page, passage = hits[0]
        # Widen to the neighbouring paragraphs under the same heading (lists, follow-on sentences).
        passage = self._with_neighbours(page, passage)
        # Answer from one page only (its best two passages), so no other page's numbers leak in.
        extra = next((c for s, p, c in hits[1:] if p is page and s >= 0.6 * top
                      and c not in passage and passage not in c), None)
        text = passage if not extra else f"{passage} {extra}"
        return Answer(text=text[:900],
                      sources=[Source(url=page.url, snapshot_id=page.snapshot_id, quote=passage[:200])])

    @staticmethod
    def _with_neighbours(page, passage, limit=700):
        try:
            i = page.chunks.index(passage)
        except ValueError:
            return passage
        head = passage.split(": ", 1)[0] + ": " if ": " in passage else ""
        out = passage
        for j in (i - 1, i + 1):
            if 0 <= j < len(page.chunks):
                c = page.chunks[j]
                if head and c.startswith(head) and " | " not in c and len(c) < 400 and c not in out:
                    body = c[len(head):]
                    if body in out:
                        continue
                    if len(out) + len(body) > limit:
                        continue
                    out = (head + body + " " + out[len(head):]) if j < i else (out + " " + body)
        return out

    # -- routes -------------------------------------------------------------------------------
    @staticmethod
    def _src(page, quote=None):
        return [Source(url=page.url, snapshot_id=page.snapshot_id, quote=quote)]

    def _link(self, q, view):
        if not LINK_INTENT.search(q) or not re.search(r"\b(link|url|website|web ?page|online|site)\b", q, re.I):
            return None
        if not re.search(r"\b(link|url|which|what|where|how)\b", q, re.I):
            return None
        url = self.linkbooks[view.snapshot_id].best(q)
        if not url:
            return None
        return Answer(text=f"You can use {url}", sources=[Source(url=url, snapshot_id=view.snapshot_id)])

    BRANCH_NAME = re.compile(r"\b((?:[A-Z][\w'.&-]*\s+){1,3})[Bb]ranch\b")

    def _named_branch(self, q):
        m = self.BRANCH_NAME.search(q)
        if not m:
            return None
        name = " ".join(w for w in m.group(1).split() if w.lower() not in {"the", "dupaco", "dupaco's", "your", "what", "is"})
        return name or None

    def _hours(self, q, view):
        if not re.search(r"\bhours?\b", q, re.I):
            return None
        name = self._named_branch(q)
        if name:
            # Hours for one branch are only trusted from a page that names that branch.
            for page in sorted(view.pages.values(), key=lambda p: (-p.tier, p.key)):
                if name.lower() in page.title.lower() and directory.hours_blocks(page):
                    blocks = directory.hours_blocks(page)
                    text = f"{name} branch hours: " + " ".join(f"{k.title()}: {s}." for k, s in blocks)
                    return Answer(text=text, sources=self._src(page))
            return Answer(text=f"I couldn't find posted hours for a {name} branch on Dupaco's website, so I "
                               f"don't want to guess. Please contact Dupaco or use the branch locator.",
                          confident=False)
        summary = directory.hours_summary(view)
        if not summary:
            return None
        parts, pages = [], []
        for kind in ("lobby", "drive-up"):
            scheds = summary.get(kind) or []
            if not scheds:
                continue
            main, *others = scheds
            s = f"{kind.title()} hours at most branches: {main[0]}."
            if others:
                s += " Some branches differ: " + " | ".join(o[0] for o in others[:2]) + "."
            parts.append(s)
            pages += [main[1]] + [o[1] for o in others[:2]]
        text = ("Hours vary by branch. " + " ".join(parts) +
                " Which branch would you like hours for? The branch locator is at https://www.dupaco.com/contact")
        srcs = [Source(url="https://www.dupaco.com/contact", snapshot_id=view.snapshot_id)]
        srcs += [Source(url=u, snapshot_id=view.snapshot_id) for u in dict.fromkeys(p.url for p in pages)]
        return Answer(text=text, sources=srcs)

    def _address(self, q, view):
        if not re.search(r"\b(address|located|location of|where is)\b", q, re.I):
            return None
        name = self._named_branch(q)
        if not name:
            return None
        locator = next((p for p in view.pages.values() if p.key.endswith("dupaco.com/contact")), None)
        entries = directory.branches(locator) if locator else []
        nl = name.lower()
        hits = [e for e in entries if "atm" not in e["kind"].lower() and
                (nl in e["city"].lower() or nl in e["street"].lower() or nl in e["name"].lower())]
        if len(hits) == 1:
            e = hits[0]
            return Answer(text=f"The {name} branch is at {e['address']}.", sources=self._src(e["page"], e["address"]))
        if len(hits) > 1:
            return Answer(text=f"There are {len(hits)} branches matching {name}: " +
                               "; ".join(e["address"] for e in hits) + ".", sources=self._src(hits[0]["page"]))
        return None          # not in the locator: let the general search try (e.g. closed branches)

    PLACE = re.compile(r"\bbranch(?:es)?\s+(?:in|at|near)\s+((?:[A-Z][\w'.-]*\s?){1,3})")

    def _locator(self, view):
        page = next((p for p in view.pages.values() if p.key.endswith("dupaco.com/contact")), None)
        return page, (directory.branches(page) if page else [])

    def _branch_in(self, q, view):
        """'Is there a branch in X?': answered from the branch locator only."""
        m = self.PLACE.search(q)
        if not m:
            return None
        place = m.group(1).strip().rstrip("?.!")
        page, entries = self._locator(view)
        hits = [e for e in entries if "atm" not in e["kind"].lower() and place.lower() in
                f"{e['city']} {e['street']}".lower()]
        if hits:
            return Answer(text=f"Yes. Dupaco has {len(hits)} branch location(s) in {place}: " +
                               "; ".join(e["address"] for e in hits) + ".", sources=self._src(page))
        if page:
            return Answer(text=f"I don't see a Dupaco branch in {place} in the branch locator. Please check "
                               f"the locator at https://www.dupaco.com/contact or contact Dupaco.",
                          confident=False, sources=self._src(page))
        return None

    PHONE_Q = re.compile(r"\b(phone|call|telephone|contact number)\b", re.I)
    PHONE = re.compile(r"\b(?:1[-. ])?(\d{3})[-. ](\d{3})[-. ](\d{4})\b")

    def _phone(self, q, view):
        """The main phone number = the toll-free number most repeated on non-editorial pages."""
        if not self.PHONE_Q.search(q) or re.search(r"\b(lost|stolen|fraud|branch|after hours|routing)\b", q, re.I):
            return None
        from collections import Counter
        c = Counter()
        for p in view.pages.values():
            if p.tier >= 3:
                c.update("-".join(m) for m in self.PHONE.findall(p.markdown))
        if not c:
            return None
        num = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        page = next(p for p in sorted(view.pages.values(), key=lambda p: (-p.tier, p.key)) if num in p.markdown)
        return Answer(text=f"You can call Dupaco at {num}.", sources=self._src(page))

    STAT_Q = {
        "branches": re.compile(r"how many (?:branch(?:es)?|branch offices|locations|offices)\b(?!.*\b(?:close|closed|open(?:ed)?)\b)", re.I),
        "members": re.compile(r"how many members\b|\bmember(?:ship)? (?:count|size)\b", re.I),
        "employees": re.compile(r"how many (?:employees|people work|staff)\b(?! (?:used|volunteer|served|took))", re.I),
        "assets": re.compile(r"\b(?:total )?assets\b|how (?:big|large) is", re.I),
    }
    STAT_TEXT = {"branches": "{v} branch office locations", "members": "more than {v} members",
                 "employees": "about {v} employees", "assets": "assets of more than ${v} billion"}

    def _stats(self, q, view):
        kind = next((k for k, rx in self.STAT_Q.items() if rx.search(q)), None)
        if not kind:
            return None
        if view.snapshot_id not in self._stats_cache:
            self._stats_cache[view.snapshot_id] = directory.latest_boilerplate(view)
        rec = self._stats_cache[view.snapshot_id]
        if not rec or not rec.get(kind):
            return None
        text = f"Dupaco has {self.STAT_TEXT[kind].format(v=rec[kind])}."
        return Answer(text=text, sources=self._src(rec["page"], rec["text"][:200]),
                      conflict_note="Taken from the newest 'About Dupaco' statement (largest member count); "
                                    "older articles repeat outdated counts.")

    PROPER = re.compile(r"(?<![.?!]\s)(?<!^)\b([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*)\b")

    def _unknown_entity(self, q, view):
        """A named place/product the site never mentions → don't guess (rule R6)."""
        ignore = {"Dupaco", "I", "Can", "What", "Is", "Do", "How", "Who", "When", "Where", "Which", "Visa",
                  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "October",
                  "September", "May", "June", "July", "August", "January", "February", "March", "April",
                  "November", "December", "Please", "Tell", "Give"}
        idx = self.indexes[view.snapshot_id]
        for m in self.PROPER.finditer(q):
            phrase = m.group(1)
            ws = [w for w in re.split(r"[\s-]", phrase) if w not in ignore]
            if ws and all(idx.df(w) == 0 for w in ws):
                return phrase
        return None

    def conflicts(self):
        if self._conflicts is None:
            self._conflicts = find_conflicts(self.store, Conflict, Source)
        return self._conflicts


def build():
    return KnowledgeSystem()
