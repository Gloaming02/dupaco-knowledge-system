"""How much to trust a page (docs/RULES.md, rule R2).

Tiers are ordered: a higher number wins a disagreement within the same snapshot.
Classification is by URL only, so it is deterministic and explainable.
"""
import re

from .urls import path_of, url_key

RATE_SHEET, PRODUCT, REFERENCE, MARKETING, EDITORIAL, LEGACY = 5, 4, 3, 2, 1, 0
NAMES = {RATE_SHEET: "rate sheet", PRODUCT: "product page", REFERENCE: "reference page",
         MARKETING: "calculator/landing page", EDITORIAL: "blog/newsroom", LEGACY: "legacy page"}

_RATE_SHEETS = {"/rates", "/business-rates"}
_PRODUCT_PREFIXES = ("/personal/", "/business/", "/savings-account/", "/checking", "/contact",
                     "/about/join", "/locations")
_MARKETING = re.compile(r"^/(calculators|business-calculators)(/|$)|-lp$|^/(switch-and-earn|earn-more|"
                        r"21-day-sprint|checking-offer)")
_EDITORIAL = re.compile(r"^/(learn|newsroom|business/resources|resources|dupacodaily|20\d\d)(/|$)")


def tier(url: str) -> int:
    key = url_key(url)
    if not key.startswith("dupaco.com"):
        return LEGACY                      # info.dupaco.com and other old subdomains
    path = path_of(url)
    if path in _RATE_SHEETS:
        return RATE_SHEET
    if _MARKETING.search(path):
        return MARKETING
    if _EDITORIAL.search(path):
        return EDITORIAL
    if path.startswith(_PRODUCT_PREFIXES):
        return PRODUCT
    return REFERENCE                       # /about, /hubfs/*.pdf, policies, misc pages


def is_event_source(url: str) -> bool:
    """Newsroom is the authority for events nobody else covers (rule R2b)."""
    return path_of(url).startswith("/newsroom")
