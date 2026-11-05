"""BM25 over one snapshot's chunks, re-ranked by page authority (rule R2)."""
import math
from collections import Counter, defaultdict

from .text import tokens

K1, B = 1.2, 0.6
TIER_BOOST = 0.15          # each authority tier adds 15% to a passage's score


class SnapshotIndex:
    def __init__(self, view, token_cache: dict):
        self.docs = []                                    # (PageVersion, chunk text)
        self.postings = defaultdict(list)                 # term -> [(doc id, tf)]
        lens = []
        for page in sorted(view.pages.values(), key=lambda p: p.key):   # stable order
            for text in page.chunks:
                toks = token_cache.get(text)
                if toks is None:
                    toks = token_cache[text] = Counter(tokens(text))
                doc_id = len(self.docs)
                self.docs.append((page, text))
                lens.append(sum(toks.values()))
                for t, tf in toks.items():
                    self.postings[t].append((doc_id, tf))
        self.lens = lens
        self.avg = (sum(lens) / len(lens)) if lens else 1.0
        n = len(lens)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def df(self, word: str) -> float:
        """Share of passages containing `word` (unstemmed)."""
        toks = tokens(word)
        if not toks:
            return 1.0          # a stop word: treat as common
        return min(len(self.postings.get(t, ())) for t in toks) / max(1, len(self.docs))

    def search(self, query: str, k: int = 10):
        scores = defaultdict(float)
        for t in set(tokens(query)):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for d, tf in self.postings[t]:
                scores[d] += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * self.lens[d] / self.avg))
        ranked = sorted(((s * (1 + TIER_BOOST * self.docs[d][0].tier) * _freshness(self.docs[d][0]), d)
                         for d, s in scores.items()),
                        key=lambda x: (-x[0], x[1]))
        hits = [(s, self.docs[d][0], self.docs[d][1]) for s, d in ranked[:k]]
        return prefer_newest_article(hits)


def _freshness(page) -> float:
    """Expired offers and pages missing from this crawl only win when nothing else answers."""
    return (0.5 if page.expired else 1.0) * (0.7 if page.carried else 1.0)


def prefer_newest_article(hits, window: float = 0.85):
    """Rule R3 for editorial pages: when several *articles* answer about equally well, the most
    recently published one wins ("fifth time Forbes recognized" beats "fourth time").
    Works at page level: each page's best passage competes."""
    if not hits:
        return hits
    best_per_page = {}
    for h in hits:
        best_per_page.setdefault(h[1].key, h)
    top = hits[0][0]
    close = [h for h in best_per_page.values() if h[0] >= window * top]
    if len(close) > 1 and all(h[1].tier <= 1 for h in close):
        win = max(close, key=lambda h: (h[1].printed_date or "", h[0]))
        hits = [h for h in hits if h[1].key == win[1].key] + [h for h in hits if h[1].key != win[1].key]
    return hits
