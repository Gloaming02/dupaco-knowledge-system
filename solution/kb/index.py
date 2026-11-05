"""BM25 over one snapshot's chunks, re-ranked by page authority (rule R2)."""
import math
from collections import Counter, defaultdict

from .text import tokens

K1, B = 1.2, 0.6
TIER_BOOST = 0.12          # each authority tier adds 12% to a passage's score


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
        return len(self.postings.get(word.lower(), ())) / max(1, len(self.docs))

    def search(self, query: str, k: int = 10):
        scores = defaultdict(float)
        for t in set(tokens(query)):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for d, tf in self.postings[t]:
                scores[d] += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * self.lens[d] / self.avg))
        ranked = sorted(((s * (1 + TIER_BOOST * self.docs[d][0].tier), d) for d, s in scores.items()),
                        key=lambda x: (-x[0], x[1]))
        return [(s, self.docs[d][0], self.docs[d][1]) for s, d in ranked[:k]]
