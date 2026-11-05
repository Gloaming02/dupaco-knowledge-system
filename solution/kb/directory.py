"""Branch directory, opening hours and company stats: the non-rate facts with structure."""
import re
from collections import Counter
from typing import Optional

from .urls import path_of

# ---------------------------------------------------------------- branch locations (/contact)
ADDRESS = re.compile(r"^\s*(\d+[^,\n]*?),\s*([A-Za-z .'-]+),\s*([A-Z]{2}),\s*(\d{5})\s*$", re.M)


def branches(page) -> list[dict]:
    """Entries of the branch/ATM locator: '### name' / type / 'street, city, ST, zip'."""
    out = []
    for block in re.split(r"^###\s+", page.markdown, flags=re.M)[1:]:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = next((ADDRESS.match(l) for l in lines[1:4] if ADDRESS.match(l)), None)
        if not m:
            continue
        kind = lines[1] if not ADDRESS.match(lines[1]) else ""
        out.append({"name": lines[0].replace("\\", ""), "kind": kind, "street": m.group(1),
                    "city": m.group(2).strip(), "state": m.group(3), "zip": m.group(4),
                    "address": f"{m.group(1)}, {m.group(2).strip()}, {m.group(3)} {m.group(4)}",
                    "page": page})
    return out


# ---------------------------------------------------------------- hours blocks
DAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*"
HOURS_LINE = re.compile(rf"^\s*({DAY}(?:\s*[-–]\s*{DAY})?)\s*:\s*(.+?)\s*$", re.I | re.M)
BLOCK = re.compile(r"\*\*\s*(lobby|drive[- ]?up)\s*\*\*", re.I)


def hours_blocks(page) -> list[tuple]:
    """[(kind, 'Monday-Friday: 8:30 a.m.–5:30 p.m.; Saturday: …')] found on a page."""
    out = []
    md = page.markdown
    for m in BLOCK.finditer(md):
        kind = "lobby" if m.group(1).lower().startswith("lobby") else "drive-up"
        tail = md[m.end():m.end() + 400]
        tail = re.split(r"\*\*", tail)[0]                 # stop at the next bold header
        lines = [f"{d.strip()}: {t.strip()}" for d, t in HOURS_LINE.findall(tail)]
        if lines:
            out.append((kind, "; ".join(lines)))
    return out


def _norm_sched(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("–", "-").replace("—", "-")).strip()


def hours_summary(view) -> Optional[dict]:
    """All distinct lobby / drive-up schedules on the site, most common (then newest) first."""
    seen = {"lobby": Counter(), "drive-up": Counter()}
    newest, src = {}, {}
    for page in view.pages.values():
        for kind, sched in hours_blocks(page):
            k = _norm_sched(sched)
            seen[kind][k] += 1
            d = page.printed_date or ""
            if d >= newest.get((kind, k), ""):
                newest[(kind, k)], src[(kind, k)] = d, page
    if not any(seen.values()):
        return None
    res = {}
    for kind, c in seen.items():
        res[kind] = [(s, src[(kind, s)]) for s, _ in
                     sorted(c.items(), key=lambda kv: (-kv[1], newest[(kind, kv[0])][::-1], kv[0]))]
    return res


# ---------------------------------------------------------------- company stats (rule R3b)
BOILER = {
    "members": re.compile(r"(?:more than|over|nearly|approximately)\s+([\d,]{5,})\s+(?:members|member-owners)|"
                          r"membership has grown to (?:more than |over |nearly )?([\d,]{5,})", re.I),
    "branches": re.compile(r"\b(\d{1,2})\s+branch(?:es| office locations| offices| locations)\b", re.I),
    "employees": re.compile(r"(?:over|nearly|more than|approximately)?\s*([\d,]{3,})\s+employees", re.I),
    "assets": re.compile(r"assets (?:exceeding|of more than|of over|of)\s+\$([\d.]+)\s+billion", re.I),
}


def boilerplates(view) -> list[dict]:
    """Every 'About Dupaco' style paragraph with its numbers and page."""
    out = []
    for page in view.pages.values():
        for para in re.split(r"\n\s*\n", page.markdown):
            if not BOILER["members"].search(para) or "branch" not in para.lower():
                continue
            rec = {"page": page, "text": re.sub(r"\s+", " ", para).strip()}
            for k, rx in BOILER.items():
                m = rx.search(para)
                if m:
                    rec[k] = next(g for g in m.groups() if g)
            out.append(rec)
    return out


def latest_boilerplate(view) -> Optional[dict]:
    """Newest company stats: the paragraph with the largest member count (member counts only
    grow), then the newest printed date. Never a majority vote."""
    recs = [r for r in boilerplates(view) if r.get("members") and r.get("branches")]
    if not recs:
        return None
    return max(recs, key=lambda r: (int(r["members"].replace(",", "")), r["page"].printed_date or "",
                                    path_of(r["page"].url)))
