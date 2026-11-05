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


def _domain(host: str) -> str:
    parts = host.lower().split(":")[0].split(".")
    return ".".join(parts[-2:])


class LinkBook:
    def __init__(self, view):
        self.view = view
        hosts = defaultdict(int)
        for p in view.pages.values():
            hosts[_domain(urlparse(p.url).netloc)] += 1
        self.domain = max(hosts, key=hosts.get) if hosts else ""
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
                core = {w for w in qs - {"rate"} if any(w in tokens(s) for s in secs)} or (qs - {"rate"})
                if core and any(core <= set(tokens(s)) for s in secs):
                    lists_it = 0.2                     # the page carries that product's rate table
            hit = len(qs & words) / len(qs)
            if hit < 0.5:
                continue
            host = path.netloc.lower()
            own = _domain(host) == self.domain
            main_host = host.removeprefix("www.") == self.domain
            alive = page is not None or not main_host       # a main-site page missing from the crawl is dead
            total = sum(t["anchors"].values())
            # Share of the links to this target whose anchor text itself names what was asked.
            anchor_share = sum(n for a, n in t["anchors"].items() if qs & set(tokens(a))) / max(1, total)
            action = 0.0
            if ACTION_Q.search(question):
                # "join online" wants the application, not the page about joining.
                action = 0.3 * sum(n for a, n in t["anchors"].items() if ACTION_ANCHOR.match(a)) / max(1, total)
            score = (hit + lists_it + 0.2 * anchor_share + action + 0.05 * min(t["n"], 10) / 10
                     + (0.1 if alive else -0.5) - (0.5 if LEGACY_HOST.match(host) else 0))
            scored.append((score, -len(url), url, own))
        if not scored:
            return None
        if any(o for *_, o in scored):
            scored = [x for x in scored if x[3]]          # never send members off the site's own domain
        scored.sort(reverse=True)
        return [u for s, _, u, _ in scored[:2] if s >= scored[0][0] - 0.1]


LEGACY_HOST = re.compile(r"^(info|old|legacy|archive)\.")
ACTION_Q = re.compile(r"\b(apply|sign up|enroll|open an? (?:account|membership)|join|become a member)\b", re.I)
ACTION_ANCHOR = re.compile(r"(become|apply|open|start|join|sign up|enroll|get started|continue my application)\b", re.I)
SYN_MAP = {"cd": "certificate", "cds": "certificates", "mortgage": "home loan", "atm": "atm"}
SYN = re.compile(r"\b(cds?|mortgage)\b", re.I)
INTENT_WORDS = {"link", "url", "website", "web", "page", "webpage", "address", "online", "site", "use",
                "see", "find", "go", "should", "where", "which", "show", "shows", "view", "check",
                "can", "could", "do", "does", "get", "there", "is", "are", "the", "my", "your", "dupaco"}
