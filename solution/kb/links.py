"""'What link should I use for X?': rank the site's own links by what they point at (rule R7).

Every markdown link on every page in the snapshot is a vote for (anchor text -> target URL).
A target scores by how well its anchor texts, URL path and (if crawled) page title match the
question. Targets that are legacy subdomains or missing from the snapshot (dead / moved
pages) are pushed down, so old links lose to the live page."""
import re
from collections import defaultdict
from urllib.parse import urlparse

from .text import tokens
from .urls import url_key

LINK = re.compile(r"(?<!!)\[([^\]]{2,120})\]\((https?://[^)\s]+)\)")
INTENT = re.compile(r"\b(link|url|website|web ?page|web address|online|site)\b", re.I)
URL_STOP = {"https", "http", "www", "com", "dupaco", "hslang", "en", "html", "pdf"}


def canonical(url: str) -> str:
    p = urlparse(url)
    frag = f"#{p.fragment}" if p.fragment and not p.fragment.startswith("dupaco-locator-widget") and len(p.fragment) < 20 else ""
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/') or '/'}{frag}"


class LinkBook:
    def __init__(self, view):
        self.view = view
        self.targets = defaultdict(lambda: {"anchors": defaultdict(int), "n": 0})
        for page in sorted(view.pages.values(), key=lambda p: p.key):
            for text, href in LINK.findall(page.markdown):
                if "mailto:" in href or "#" == href[-1:]:
                    continue
                t = self.targets[canonical(href)]
                t["anchors"][re.sub(r"[*_]", "", text).strip().lower()] += 1
                t["n"] += 1

    def best(self, question: str):
        q = [w for w in tokens(SYN.sub(lambda m: SYN_MAP[m.group(0).lower()], question)) if w not in INTENT_WORDS]
        if not q:
            return None
        qs = set(q)
        scored = []
        for url, t in self.targets.items():
            words = set()
            for a in t["anchors"]:
                words |= set(tokens(a))
            path = urlparse(url)
            words |= set(tokens(" ".join(w for w in re.split(r"[^a-z0-9]+", (path.netloc + path.path + " " + path.fragment).lower())
                                         if w and w not in URL_STOP)))
            page = self.view.pages.get(url_key(url))
            lists_it = 0.0
            if page:
                words |= set(tokens(page.title))
                secs = {f.section.split(" / ")[-1] for f in page.facts}
                for s in secs:                         # what the target page actually lists
                    words |= set(tokens(s))
                core = qs - {"rate"}
                if core and any(core <= set(tokens(s)) for s in secs):
                    lists_it = 0.2                     # the page carries that product's rate table
            hit = len(qs & words) / len(qs)
            if hit < 0.5:
                continue
            host = path.netloc.lower()
            alive = page is not None or host not in ("www.dupaco.com", "dupaco.com")
            score = hit + lists_it + 0.05 * min(t["n"], 10) / 10 + (0.1 if alive else -0.5) - (0.5 if host.startswith("info.") else 0)
            scored.append((score, -len(url), url))
        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][2]


SYN_MAP = {"cd": "certificate", "cds": "certificates", "mortgage": "home loan", "atm": "atm"}
SYN = re.compile(r"\b(cds?|mortgage)\b", re.I)
INTENT_WORDS = {"link", "url", "website", "web", "page", "webpage", "address", "online", "site", "use",
                "see", "find", "go", "should", "where", "which"}
