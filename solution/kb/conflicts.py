"""conflicts(): every place the website contradicts itself, with the value we trust and why.

A contradiction is two observations of the *same fact key* with different values, either on
different pages of one snapshot (a stale calculator next to the rate sheet) or on the same
page across snapshots (the rate moved and an old copy lingered). Different terms, tiers,
model-year groups or metrics are different facts, not conflicts (rule R4).

To keep precision high we only compare facts whose product we can name with confidence
(a known product family); anything else is too ambiguous to call a contradiction.
"""
import re
from collections import defaultdict

from . import authority
from .directory import boilerplates

FAMILIES = [  # (family id, label, pattern over section + row name); first match wins
    ("atv", "ATV/snowmobile loan", r"atv|snowmobile|jet ski"),
    ("boat", "boat & RV loan", r"boat|\brv\b"),
    ("auto", "auto loan", r"auto|vehicle|motorcycle"),
    ("heloc", "home equity line of credit", r"heloc|line of credit"),
    ("home_equity_loan", "home equity loan", r"home equity loan"),
    ("home_improvement", "home improvement loan", r"home improvement"),
    ("mortgage_refi", "mortgage refinance", r"refinance"),
    ("mortgage", "mortgage", r"home loans?|mortgage|purchase:"),
    ("personal_loan", "personal loan", r"personal loan"),
    ("student_loan", "student loan", r"student"),
    ("visa_rewards", "Rewards Visa", r"rewards visa"),
    ("visa_platinum", "Platinum Visa", r"platinum visa"),
    ("cert_special", "certificate special", r"special"),
    ("cert", "certificate", r"certificate|\bmonths?\b"),
    ("share_savings", "Share Savings", r"share savings"),
    ("high_yield", "High-Yield Savings", r"high[- ]yield"),
    ("bright_savings", "Bright Savings", r"bright savings"),
    ("you_name_it", "You Name It Savings", r"you name it"),
    ("holiday_club", "Holiday Club Savings", r"holiday club"),
    ("hsa", "Health Savings Account", r"health savings"),
    ("money_market", "money market", r"money market"),
    ("launchpad", "Launchpad Savings", r"launchpad"),
    ("first_rate_checking", "1st Rate Checking", r"1st rate checking"),
    ("free_checking", "Free Checking", r"free checking"),
]
_FAM = [(fid, label, re.compile(rx, re.I)) for fid, label, rx in FAMILIES]


def family(f):
    text = f"{f.section.split(' / ')[-1]} {f.name}"
    for fid, label, rx in _FAM:
        if rx.search(text):
            return fid, label
    return None, None


def _num(v: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", v)
    return round(float(m.group()), 3) if m else -1.0


def _year_ranks(facts):
    """Model-year groups ranked newest-first within each page's table, so the calculator's
    "2023-26" and the rate sheet's "2024-27" are both "newest model years" (rank 0)."""
    ranks = {}
    by_table = defaultdict(set)
    for f in facts:
        if f.years:
            by_table[(id(f.page), f.section)].add(f.years)
    for table, bands in by_table.items():
        for i, b in enumerate(sorted(bands, key=lambda b: (-b[1], -b[0]))):
            ranks[(table, b)] = i
    return ranks


YEAR_RANK_LABEL = ["newest model years", "second model-year group", "third model-year group",
                   "fourth model-year group", "oldest model years"]


def _key(f, fam, ranks):
    metric = "apr" if f.is_loan else "apy"
    if metric not in f.values:
        return None, None
    yr = ranks.get(((id(f.page), f.section), f.years)) if f.years else None
    variant = tuple(sorted(f.flags & {"jumbo", "refinance", "variable", "intro"}))
    key = (fam, f.audience, f.ira_kind, f.term, yr, f.amount, variant, metric)
    return key, metric


def _topic(f, label, yr, metric):
    bits = []
    if f.audience == "business":
        bits.append("business")
    if f.ira_kind:
        bits.append(f"{f.ira_kind.title()} IRA")
    if f.term:
        bits.append(f"{f.term // 12}-year" if f.term >= 120 and f.term % 12 == 0 else f"{f.term}-month")
    if "jumbo" in f.flags:
        bits.append("jumbo")
    bits.append(label)
    if yr is not None:
        bits.append(f"({YEAR_RANK_LABEL[min(yr, 4)]})")
    if f.tier_label:
        bits.append(f"[{f.tier_label}]")
    elif f.amount and f.amount[0] == 0:
        bits.append(f"[up to ${f.amount[1]:,.0f}]")
    elif f.amount and f.amount[1] == float("inf") and f.amount[0] >= 1000:
        bits.append(f"[${f.amount[0]:,.0f}+]")
    return " ".join(bits) + f" {metric.upper()}"


def find(store, Conflict, Source) -> list:
    obs = defaultdict(list)          # key -> [(snapshot index, fact, value)]
    sample = {}
    for si, view in enumerate(store.snapshots):
        facts = [f for p in view.pages.values() if not p.carried for f in (p.facts + p.stale_facts)]
        ranks = _year_ranks(facts)
        for f in facts:
            fam, label = family(f)
            if not fam:
                continue
            key, metric = _key(f, fam, ranks)
            if not key:
                continue
            if f.is_loan and _num(f.values[metric]) == 0:
                continue                      # a 0.00% APR is an empty template cell, not a rate
            obs[key].append((si, f, f.values[metric]))
            sample.setdefault(key, (f, label, key[4], metric))

    out, mirrored = [], set()
    latest_i = len(store.snapshots) - 1
    # The same product is repeated for business and IRA audiences with identical numbers;
    # report it once (under the personal key when there is one) to keep the list precise.
    by_shape = defaultdict(list)
    for key, rows in obs.items():
        vals = frozenset(_num(v) for _, _, v in rows)
        if len(vals) > 1:
            shape = (key[0],) + key[3:] + (vals,)
            by_shape[shape].append(key)
    for keys in by_shape.values():
        keep = min(keys, key=lambda k: ({"personal": 0, "ira": 1, "business": 2}[k[1]], str(k)))
        mirrored |= set(keys) - {keep}
    for key in sorted(obs, key=str):
        if key in mirrored:
            continue
        rows = obs[key]
        values = {}
        for si, f, v in rows:
            values.setdefault(_num(v), v)
        if len(values) < 2:
            continue
        last_si = max(si for si, _, _ in rows)
        current = [(f, v) for si, f, v in rows if si == last_si]
        win_f, win_v = max(current, key=lambda fv: (not fv[0].page.expired, fv[0].page.tier,
                                                    fv[0].page.printed_date or "", fv[0].page.key))
        stale = sorted({(v, f.page.url) for si, f, v in rows if _num(v) != _num(win_v)})
        same_snapshot = sorted({(v, f.page.url) for f, v in current if _num(v) != _num(win_v)})
        f0, label, yr, metric = sample[key]
        expired = sorted({(v, f.page.url) for f, v in current if f.page.expired and _num(v) != _num(win_v)})
        if expired and not [x for x in same_snapshot if x not in expired]:
            why = (f"{win_v} on {win_f.page.url} is current; "
                   + "; ".join(f"{u} shows {v} but that offer has ended" for v, u in expired[:3]) + ".")
        elif same_snapshot:
            why = (f"In the {store.snapshots[last_si].taken_on} snapshot the "
                   f"{authority.NAMES[win_f.page.tier]} {win_f.page.url} says {win_v}; "
                   + "; ".join(f"{u} still shows {v}" for v, u in same_snapshot[:3])
                   + ". The more authoritative / newer-dated page wins.")
        else:
            olds = sorted({v for v, _ in stale}, key=_num)
            why = (f"Value changed over time: earlier snapshots showed {', '.join(olds)}; the newest "
                   f"snapshot ({store.snapshots[last_si].taken_on}) shows {win_v} on {win_f.page.url}.")
        if last_si != latest_i:
            why += " (Not present in the latest snapshot; resolution is the last value seen.)"
        srcs = [Source(url=win_f.page.url, snapshot_id=win_f.page.snapshot_id, quote=win_f.text[:160])]
        seen = {win_f.page.url}
        for si, f, v in rows:
            if _num(v) != _num(win_v) and f.page.url not in seen:
                seen.add(f.page.url)
                srcs.append(Source(url=f.page.url, snapshot_id=f.page.snapshot_id, quote=f.text[:160]))
        out.append(Conflict(topic=_topic(f0, label, yr, metric),
                            values=[values[k] for k in sorted(values)],
                            sources=srcs[:6], resolution=win_v, reason=why))
    out += _stat_conflicts(store, Conflict, Source)
    return out


def _stat_conflicts(store, Conflict, Source) -> list:
    """Company stats repeated in old press-release boilerplate (rule R3b): branch count."""
    view = store.snapshots[-1]
    recs = [r for r in boilerplates(view) if r.get("branches") and r.get("members")]
    vals = sorted({r["branches"] for r in recs}, key=int)
    if len(vals) < 2:
        return []
    win = max(recs, key=lambda r: (int(r["members"].replace(",", "")), r["page"].printed_date or "", r["page"].key))
    srcs = [Source(url=win["page"].url, snapshot_id=view.snapshot_id, quote=win["text"][:160])]
    for v in vals:
        r = next(r for r in recs if r["branches"] == v)
        if r is not win:
            srcs.append(Source(url=r["page"].url, snapshot_id=view.snapshot_id, quote=r["text"][:160]))
    return [Conflict(topic="number of Dupaco branch offices",
                     values=[f"{v} branch offices" for v in vals],
                     sources=srcs[:6], resolution=f"{win['branches']} branch offices",
                     reason=(f"Press-release boilerplate repeats old counts. The newest statement "
                             f"(largest member count, {win['members']} members) says {win['branches']}; "
                             f"a majority vote would pick a stale value."))]
