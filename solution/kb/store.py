"""Every version of every page, keyed by (snapshot, url). Nothing is overwritten:
history is what lets us answer `as_of` questions and explain conflicts."""
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from typing import Optional

from . import authority, dates
from .facts import extract
from .text import chunks
from .urls import url_key


@dataclass
class PageVersion:
    url: str
    key: str
    title: str
    markdown: str
    snapshot_id: str
    taken_on: str
    tier: int
    printed_date: Optional[str]
    chunks: list = field(default_factory=list)
    facts: list = field(default_factory=list)
    carried: bool = False          # not in this crawl; last version seen in an earlier one
    expired: bool = False          # the page says its offer ended before this snapshot
    stale_facts: list = field(default_factory=list)   # facts of an expired page (for conflicts only)


@dataclass
class SnapshotView:
    snapshot_id: str
    taken_on: str
    pages: dict  # url_key -> PageVersion


class Store:
    def __init__(self):
        self.snapshots: list[SnapshotView] = []          # oldest -> newest
        self._sheet_rows: set[str] = set()                # row names ever listed on a rate sheet
        self._chunk_cache: dict[int, list] = {}           # identical text is chunked once

    def add(self, snapshot) -> SnapshotView:
        view = SnapshotView(snapshot.snapshot_id, snapshot.taken_on, {})
        for p in snapshot.pages:
            key = url_key(p.url)
            h = hash((p.title, p.markdown))
            if h not in self._chunk_cache:
                self._chunk_cache[h] = chunks(p.markdown, p.title)
            prev = view.pages.get(key)
            if prev and len(prev.markdown) >= len(p.markdown):
                continue                                   # duplicate URL spellings: keep the fuller one
            view.pages[key] = PageVersion(
                url=p.url.split("?")[0], key=key, title=p.title, markdown=p.markdown,
                snapshot_id=snapshot.snapshot_id, taken_on=snapshot.taken_on,
                tier=authority.tier(p.url), printed_date=dates.page_date(p.markdown),
                chunks=self._chunk_cache[h])
            pv = view.pages[key]
            ends = dates.end_dates(p.markdown)
            pv.expired = bool(ends) and max(ends) < snapshot.taken_on
            pv.facts = [] if pv.expired else extract(pv)
            pv.stale_facts = extract(pv) if pv.expired else []
        # Pages missing from this crawl are carried forward (flagged) from the previous view:
        # a crawl can simply miss a page. Present pages always outrank carried ones.
        if self.snapshots:
            for key, old in self.snapshots[-1].pages.items():
                if key not in view.pages:
                    new = replace(old, carried=True)
                    new.facts = [replace(f, page=new) for f in old.facts]
                    view.pages[key] = new
        self._withdraw(view)
        self.snapshots.append(view)
        self.snapshots.sort(key=lambda s: s.taken_on)
        return view

    def _withdraw(self, view: SnapshotView) -> None:
        """Rule R5: a row the rate sheet used to list and no longer does was withdrawn. Other
        pages that still show it (a landing page, a guide) are stale: their copy is kept for
        conflicts() but no longer answers questions."""
        def row(f):
            return "".join(c for c in f.name.lower() if c.isalnum())
        sheets = [p for p in view.pages.values() if p.tier == authority.RATE_SHEET and not p.carried]
        if not sheets:
            return
        listed = {row(f) for p in sheets for f in p.facts}
        withdrawn = self._sheet_rows - listed
        self._sheet_rows |= listed
        for p in view.pages.values():
            if p.tier != authority.RATE_SHEET and any(row(f) in withdrawn for f in p.facts):
                p.stale_facts = p.stale_facts + [f for f in p.facts if row(f) in withdrawn]
                p.facts = [f for f in p.facts if row(f) not in withdrawn]

    def at(self, as_of: Optional[str] = None) -> SnapshotView:
        """Rule R1: no date -> latest; a date -> newest snapshot taken on or before it
        (the earliest snapshot if the date predates them all)."""
        day = dates.as_of_date(as_of)
        if not day:
            return self.snapshots[-1]
        days = [s.taken_on for s in self.snapshots]
        return self.snapshots[max(0, bisect_right(days, day) - 1)]

    def history(self, key: str) -> list[PageVersion]:
        """All versions of one page, oldest first (absent snapshots skipped)."""
        return [s.pages[key] for s in self.snapshots if key in s.pages]
