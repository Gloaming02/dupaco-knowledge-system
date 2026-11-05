"""Every version of every page, keyed by (snapshot, url). Nothing is overwritten:
history is what lets us answer `as_of` questions and explain conflicts."""
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Optional

from . import authority, dates
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


@dataclass
class SnapshotView:
    snapshot_id: str
    taken_on: str
    pages: dict  # url_key -> PageVersion


class Store:
    def __init__(self):
        self.snapshots: list[SnapshotView] = []          # oldest -> newest
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
        self.snapshots.append(view)
        self.snapshots.sort(key=lambda s: s.taken_on)
        return view

    def at(self, as_of: Optional[str] = None) -> SnapshotView:
        """Rule R1: no date -> latest; a date -> newest snapshot taken on or before it
        (the earliest snapshot if the date predates them all)."""
        if not as_of:
            return self.snapshots[-1]
        days = [s.taken_on for s in self.snapshots]
        i = bisect_right(days, str(as_of)[:10])
        return self.snapshots[max(0, i - 1)]

    def history(self, key: str) -> list[PageVersion]:
        """All versions of one page, oldest first (absent snapshots skipped)."""
        return [s.pages[key] for s in self.snapshots if key in s.pages]
