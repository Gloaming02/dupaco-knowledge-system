# NOTES

**No API keys. No network calls. Standard library only** (Python 3.11). Ingesting all five
snapshots takes about 5 s, and answers take milliseconds (p95 about 20 ms). Every answer is
deterministic.

## Approach in one paragraph

The system is deliberately **rules + retrieval, not an LLM**. The scorer zeroes any answer that
contains a stale or wrong-tier number. Consistency is measured on the exact set of numbers in
the text. Speed is judged at p95 ≤ 2 s. So the job is mostly *deciding which value is true*.
That decision should be explicit, auditable and repeatable, and an LLM adds variance on exactly
that step. Instead, every page version is kept with its snapshot and printed dates. Rate tables
(and short "label: 3.50%" lines) are parsed into **facts with a full key** (product, audience,
term, model-year group, amount tier, variant, metric), and a fixed precedence decides which
observation wins. Free-text questions go through BM25 over the chosen snapshot, re-ranked by
the same authority and recency rules.

## How "current" is decided

The full rules are in [`docs/RULES.md`](../docs/RULES.md), each with the real case behind it.
The short version:

1. **Time first (R1).** No `as_of` means the latest snapshot. With `as_of=D`, use the newest
   snapshot taken on or before D. Only that snapshot is evidence for the answer.
2. **Authority (R2).** Page tier comes from URL patterns: rate sheet (`/rates`) > product page >
   reference page > calculator/landing/promo > blog/newsroom > legacy subdomain (`info.`).
   The newsroom is still valid for events no other page covers (a branch closure).
3. **Printed date, never crawl date (R3).** Every page is re-fetched on every crawl, so
   `fetched_at` says nothing about freshness. "Effective as of", then publish date, then
   "updated" break ties within a tier. Among equally relevant articles, the newest wins (the
   "fifth time Forbes recognized" release beats the "fourth time" one).
4. **Company stats (R3b).** Press releases end with an "About Dupaco" paragraph that repeats
   whatever the counts were at the time. For branch, member and employee counts we use the
   paragraph with the **largest member count**, because membership only grows. A majority vote
   would be wrong here: "23 branches" appears 42× and the current figure, 22, appears 37×.
5. **Qualifiers are part of the key (R4).** Term, balance tier, model-year group, rate vs
   APY vs APR, personal vs business vs IRA, jumbo, refinance and intro rates are different
   facts, never conflicts. Cell contents beat headers: the vehicle calculator labels an APR
   column "Annual Percentage Yield".
6. **Expired is expired (R5).** A page that says its offer ended before the snapshot date
   is excluded from answers (its values are still reported as conflicts).
7. **Missing pages.** A page absent from a crawl is carried forward from the previous
   snapshot, but any page actually present in the crawl outranks it.
8. **Honest refusal (R6).** The system refuses with `confident=False` and no digits in the text
   (the scorer counts a phone number as a number) when:
   - a rate question matches no current rate table,
   - an unknown word modifies the product noun ("**construction** loan", "**adjustable**-rate mortgage"),
   - a named branch has no posted hours, or
   - a named entity appears nowhere on the site.

## Answer paths (`solution.py`)

| Route | When | Source of truth |
|---|---|---|
| link | "what link / URL / website…" | every link on the site, scored by anchor text, URL and what the target page lists; dead or legacy targets lose |
| hours | "hours" | lobby/drive-up blocks found on the site: the common schedule plus variants, then ask which branch |
| address / branch in X | "address of the X branch", "branch in X" | the `/contact` branch locator |
| phone | "phone / call" | the toll-free number repeated most on non-editorial pages |
| stats | "how many branches / members / employees", "assets" | newest boilerplate (R3b) |
| rates | rate/APY/APR intent | `kb/rates.py`, the structured fact lookup (below); "did it change?" questions also get a dated history |
| passage | everything else | BM25 → one winning page → best passage plus neighbouring paragraphs |

**Rate lookup.** Parse the question into the same key fields. Drop facts that contradict an
explicit qualifier. Score product similarity with IDF-weighted word overlap (with a few
synonyms: car→auto, CD→certificate, mortgage→home loan). Then let **one page** win by
(present in crawl, authority, printed date) and answer only from that page, so stale copies can
never leak into the text. Questions that ask for several products ("what cards do you offer")
get one winning page per audience.

**Change questions.** "Did the 10-month jumbo special change?" gets the current value plus
a dated history, e.g. "3.90% from 2026-05-12; 4.00% from 2026-09-28". The history is built
from rate-sheet and product pages only, so a stale calculator never enters it. Rows are
matched across snapshots by the same normalised fact key the conflict detector uses, because
row labels change between crawls (the "2023–26" model-year band became "2024-27"). With
`as_of`, the history stops at that date.

## Conflicts (`kb/conflicts.py`)

Every observation of every fact is grouped by key across all pages and snapshots, and a key
with more than one value is a conflict.
- **Within a snapshot:** a stale calculator or landing page next to the rate sheet.
- **Across snapshots:** the rate moved.

Model-year bands are ranked newest-first within each table, so the calculator's "2023–26"
and the rate sheet's "2024-27" compare as the same "newest model years" fact.

To keep precision up, these are excluded:
- products we can't name with confidence,
- `0.00%` loan cells (empty templates),
- intro and balance-transfer rates (compared against standard APRs),
- business/IRA mirrors with identical numbers.

`resolution` is the value of the most authoritative, newest-dated, non-expired page in the
latest snapshot that has the fact. `reason` says which rule decided it. The branch-count
boilerplate conflict is reported too.

## Testing

- `python harness/run_eval.py --submission solution --eval eval/public_eval.jsonl` gives final
  0.88 (qa 0.88, consistency 1.00, speed 1.00, 0 stale-value hits). No conflict gold is shipped
  for the public set.
- **Stress tests** (`tests/`), written because the hidden set is larger and reworded:
  - `paraphrase_eval.jsonl`: two rewordings of every public question, grouped with the
    original. qa 0.91, paraphrase consistency 0.90, 0 stale hits.
  - `fact_sweep.py`: one generated question for **every rate-sheet row in every snapshot**
    (663 questions, each asked with that snapshot's `as_of`). 100% contain the right value, and
    0 contain another snapshot's value for the same row.
  - `load_test.py`: 1,500 uncached questions give p95 25 ms. 144 odd input combinations (empty,
    5,000 chars, emoji, SQL, other languages, bad dates, non-strings) raise 0 errors. Ingest
    takes about 5 s and about 300 MB.
- `scripts/eval.sh solution selftest` runs the kit's synthetic site, where qa, conflict F1 and
  resolution are all 1.00. That site uses different URLs and prose-style rates, which is how
  we check the rules aren't Dupaco-specific.
- `scripts/probe.py` holds our own questions outside the public set (other products, other
  terms, `as_of`, products the site doesn't offer). We used it to catch overfitting.

## Known limits / next steps

- Free-text answers are extractive (the best passage plus neighbours). An LLM could rewrite
  the *already chosen* passage into a cleaner sentence, constrained to the numbers it contains,
  without changing which fact wins. I left it out to keep the system key-free and deterministic.
- Yes/no questions about a specific number ("does any tier pay 0.35%?") are not specially
  handled.
- Off-topic chit-chat ("tell me a joke") can still get a passage back. Lexical overlap can't
  separate it from real but conversational questions, so the relevance floor is deliberately
  low and only catches clearly unrelated input. An intent classifier (or an LLM gate) would be
  the right fix.
- The URL authority tiers are patterns, not a learned model. A new site section needs a
  pattern if it should rank above "reference".
