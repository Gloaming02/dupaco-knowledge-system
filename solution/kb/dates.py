"""Dates printed on a page (rule R3). The crawl date is useless for freshness because every
page is re-fetched on every crawl, so we read what the page itself says."""
import re
from typing import Optional

_MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_MDY = r"(\d{1,2})/(\d{1,2})/(\d{2,4})"
_LONG = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})"

EFFECTIVE = re.compile(r"effective\s+(?:as\s+of\s+)?(?:" + _MDY + "|" + _LONG + ")", re.I)
UPDATED = re.compile(r"\bupdated:?\s+(?:as of\s+)?(?:" + _MDY + "|" + _LONG + ")", re.I)
BYLINE = re.compile(r"^\s*" + _LONG + r"\s*$", re.I | re.M)
PUBLISHED_JSON = re.compile(r'"(?:datePublished|Published)"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def _iso(groups) -> Optional[str]:
    g = [x for x in groups]
    try:
        if g[0] is not None:                       # MM/DD/YY(YY)
            m, d, y = int(g[0]), int(g[1]), int(g[2])
        else:                                      # Month DD, YYYY
            m, d, y = _MONTHS[g[3][:3].lower()], int(g[4]), int(g[5])
        y = y + 2000 if y < 100 else y
        if 1 <= m <= 12 and 1 <= d <= 31 and 1990 <= y <= 2100:
            return f"{y:04d}-{m:02d}-{d:02d}"
    except (TypeError, ValueError, KeyError):
        pass
    return None


def effective_dates(text: str) -> list[str]:
    return sorted({d for x in EFFECTIVE.finditer(text) if (d := _iso(x.groups()))})


def published_date(markdown: str) -> Optional[str]:
    """Byline date near the top of newsroom/blog articles ('January 06, 2026')."""
    head = markdown[:600]
    if (x := BYLINE.search(head)):
        return _iso((None, None, None) + x.groups())
    if (x := PUBLISHED_JSON.search(markdown)):
        return x.group(1)
    return None


def page_date(markdown: str) -> Optional[str]:
    """Best single 'as fresh as' date for the page: newest effective date, else the
    publish date, else the newest 'updated' date."""
    eff = effective_dates(markdown)
    if eff:
        return eff[-1]
    if (p := published_date(markdown)):
        return p
    upd = sorted({d for x in UPDATED.finditer(markdown) if (d := _iso(x.groups()))})
    return upd[-1] if upd else None


def as_of_date(value) -> Optional[str]:
    """Normalise an `as_of` to an ISO day: '2026-05-31', '2026-05-31T12:00:00', '05/31/2026',
    'May 31, 2026'. A bare month ('2026-05', 'May 2026') means the end of that month.
    None when it can't be read."""
    s = str(value or "").strip()
    if (m := re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", s)):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 31)
    elif (m := re.search(_MDY, s)) or (m := re.search(_LONG, s, re.I)):
        return _iso(m.groups() if m.re.pattern == _MDY else (None, None, None) + m.groups())
    elif (m := re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(\d{4})", s, re.I)):
        y, mo, d = int(m.group(2)), _MONTHS[m.group(1).lower()], 31
    else:
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}" if 1 <= mo <= 12 and 1 <= d <= 31 else None


_ISO = r"(\d{4})-(\d{2})-(\d{2})"
ENDED = re.compile(r"\b(?:offer\s+)?(?:ended|expired|ends|expires|valid (?:through|until)|available (?:through|until)|"
                   r"through|until)\s+(?:on\s+)?(?:" + _MDY + "|" + _LONG + "|" + _ISO + ")", re.I)


def end_dates(text: str) -> list[str]:
    out = []
    for x in ENDED.finditer(text):
        g = x.groups()
        if g[6]:
            out.append(f"{g[6]}-{g[7]}-{g[8]}")
        elif (d := _iso(g[:6])):
            out.append(d)
    return sorted(out)
