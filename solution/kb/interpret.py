"""The second tier of question understanding (optional, off by default).

The rules bind the words of a question to what the snapshot actually lists: a rate-table
section, a fee row. They are fast and deterministic, and they know when they are out of their
depth: a question with words they could not bind ("pontoon", "premium", "abroad") or with no
match at all. For exactly those questions an interpreter may be asked for a second opinion.

An interpreter is any callable

    interpret(question: str, catalog: dict) -> dict | None

where `catalog` is built from the snapshot being answered from:

    {"products": ["Auto & Motorcycle Loans", "Boat & RV Loans", ...],   # rate-table sections
     "fees":     ["Domestic wire", "International wire transfer", ...]} # fee-schedule labels

and the result may contain

    {"product": "<one of catalog['products']>"}    the product the question means
    {"fee": "<one of catalog['fees']>"}            the fee the question means
    {"listed": False}                              it asks for something the catalog lacks

Anything else, an entry that is not in the catalog, an exception or None means "no opinion",
and the rules' own answer stands. The interpreter only chooses *which listed thing* is meant;
the value, the tier, the snapshot and the winning page are still decided by the rules, so a
language model here cannot introduce a number that is not on the site.

None is shipped enabled: `build()` returns a system with no interpreter, no network calls and
no API key. To use one, set `KnowledgeSystem.interpreter` (e.g. a temperature-0 model call with
the catalog as a closed list of choices). Results are cached per question and snapshot, so the
same question always gets the same answer within a run.
"""


def checked(hint, catalog: dict) -> dict:
    """Keep only the parts of an interpreter's reply that point into the catalog."""
    if not isinstance(hint, dict):
        return {}
    out = {}
    if hint.get("product") in catalog.get("products", ()):
        out["product"] = hint["product"]
    if hint.get("fee") in catalog.get("fees", ()):
        out["fee"] = hint["fee"]
    if hint.get("listed") is False and not out:
        out["listed"] = False
    return out
