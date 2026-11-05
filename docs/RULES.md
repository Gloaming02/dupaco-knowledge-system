# What counts as "true now": the rules

These rules decide which value the system reports when the website disagrees with itself.
Each rule cites the real case in the snapshots that motivated it. They're written as an
ordered decision procedure, so the code can follow them literally and a reviewer can check
every answer against them.

---

## 0. Vocabulary

- **Fact**: one value about one thing, e.g. *60-month auto loan, 2024-27 model year, APR = 5.39%*.
- **Fact key**: everything that identifies the thing, **without the value**:
  `(product, audience, term, tier, qualifier, metric)`.
  - `product`: auto loan, share certificate special, Share Savings, Platinum Visa, branch count…
  - `audience`: personal | business | IRA (Roth / Traditional)
  - `term`: 10 month, 60 month, 30 year…
  - `tier`: balance band / minimum deposit / loan-amount band ("$100,000 jumbo", "$10,000–$24,999")
  - `qualifier`: model-year band, fixed vs variable, special vs standard…
  - `metric`: rate (dividend rate) | APY | APR
- **Observation**: a fact plus *where* (url) and *when* (snapshot id/date, plus any date
  printed on the page).

Two observations **conflict** only when they share the same fact key and have different
values. If any key field differs, they are two different facts.

---

## R1. Pick the snapshot first (time)

1. `as_of = None` → use the **latest** snapshot (05, 2026-09-28).
2. `as_of = D` → use the **newest snapshot taken on or before D**.
   If D is earlier than the first snapshot, use snapshot 01 and say so.
3. Only the chosen snapshot is evidence for the answer. Older snapshots are used only to
   *explain* a change ("was 3.90%, now 4.00%") or to fill `conflicts()`, never as the
   answer itself.

> *Why:* the 10-month jumbo special was 3.90% APY from 05-12 through 08-27 and is 4.00% on 09-28.
> "As of May 2026" → 3.90%. Asked with no date → 4.00%.

## R2. Inside a snapshot, trust the most authoritative page (source)

Each page gets an authority tier based on its URL and content. When two observations of the
same fact key disagree, the higher tier wins.

| Tier | Pages | Examples |
|---|---|---|
| **A: rate sheets** | the site-wide rate tables | `/rates`, `/business-rates` |
| **B: product pages** | the page that sells that product | `/personal/loans/auto-loans/`, `/personal/savings-account`, `/personal/loans/home-loans`, `/business/savings-accounts`, `/personal/retirement`, `/contact` |
| **C: reference pages** | general site pages, fee-schedule PDFs (`/hubfs/*.pdf`), `/about`, FAQs | |
| **D: marketing / tools** | calculators, landing pages, campaigns | `/calculators/*`, `/switch-and-earn`, `*-lp`, `/checking-offer-lp` |
| **E: editorial** | blog, newsroom, business resources | `/learn/blog/*`, `/newsroom/*`, `/business/resources/*` |
| **X: legacy** | old subdomains | `info.dupaco.com/*` |

> *Why:* in snapshot 05, `/rates`, `/personal/loans/auto-loans/` and
> `/personal/loans/auto-motorcycle-loans` say **5.39%**. `/calculators/vehicle-affordability`
> and `/switch-and-earn` still say **5.34%** (calculator stamped "effective as of 1/1/2026").
> The tier-A and tier-B pages win.

**Exception (R2b): editorial is the only source for events.** Closures, openings, awards and
program announcements often exist *only* in the newsroom. When no tier A–C page covers the
fact, a newsroom article is valid evidence. (Hy-Vee branch: "This location will close
March 31, 2026" appears only in a newsroom post.)

## R3. Same tier, still disagreeing → newest printed date wins (recency)

Use the date printed **on the page**, not the crawl date. Almost every page is re-fetched on
every crawl, so the crawl date says nothing about freshness. Signals, strongest first:

1. "effective as of MM/DD/YYYY" on rate tables (common on `/business-rates`,
   `/business/savings-accounts`, `/learn/master-your-money/homeownership/`). If a page carries
   several, use the one attached to that table.
2. Article publish date (newsroom and blog pages have a byline date, e.g. "January 06, 2026").
3. "Updated <date>".
4. No date → treat it as older than any dated page in the same tier.

**Boilerplate counts (R3b).** Press releases end with an "About Dupaco" paragraph
("…more than 181,000 members… 22 branch office locations"). For company stats (branch count,
members, employees, assets), take the boilerplate from the **most recently dated** article. When
dates tie or are missing, the paragraph with the larger member count is the newer one.
**Never majority-vote:** in snapshot 05, "23 branch offices" appears 42× and "22" appears 37×,
and 22 is correct.

## R4. Respect qualifiers: different keys are different facts (tiering)

Before comparing values, normalise the full fact key. These are **not** conflicts:

- **rate vs APY**: `3.96% | 4.00%` on one row is one product: dividend rate 3.96%, APY 4.00%.
  Answer with the metric asked for. "Interest rate" on a deposit product means APY unless
  the question says "dividend rate".
- **different term**: 48 vs 60 vs 84 months.
- **different tier**: regular ($1,000 min) vs jumbo ($100,000 min); balance bands for Share Savings.
- **different model-year band**: "2023–26" (calculator) vs "2024-27" (rates). A question about a
  2025 vehicle matches a row in both, so R2 decides which page counts, not R4.
- **personal vs business vs IRA**: "Prime Checking" vs "Prime Business Checking". Roth vs Traditional IRA.
- **purchase APR vs promotional / balance-transfer APR** on cards.

> *Why:* in snapshot 05, "3.90%" is the **regular** 10-month special, and before 09-28 it was
> the **jumbo**. Comparing bare numbers mixes the two up.

**Which tier to answer with** when the question doesn't specify:
- If the product has a "standard" or entry tier (lowest minimum, smallest loan amount), lead
  with it and name the others in words. Mortgage: lead with the up-to-$100k tier, 30-yr 7.13%.
- If the question names a tier ("jumbo", "$10,000–$24,999", "2025 vehicle"), answer only that
  row.
- Don't recite stale values or values from other tiers in the same sentence. The scorer zeroes
  any answer containing a wrong number.

## R5. Promotions and things that ended

- A promo or event with an end date before the answer date is **expired**. Say it ended,
  don't quote its rate as current. Hy-Vee branch closed **March 31, 2026**. Asked in
  October 2026, the answer is "closed on March 31, 2026" plus where to go instead.
- A landing page (tier D) that still advertises an offer missing from the tier-A rate sheet is
  treated as stale.

## R6. Say "I don't know" honestly (refusal)

Refuse (`confident=False`, short "isn't listed on our website; please contact us or visit a
branch" text, **no digits at all**) when:

- the product isn't on the site in the chosen snapshot (e.g. 7/1 ARM, construction-loan rate);
- the entity isn't on the site (e.g. a branch name that doesn't exist);
- the only evidence is tier D/E/X for a *rate* question (old blog numbers don't count as
  a current rate).

Never put a number in a refusal. The scorer fails a refusal that contains any number not
already in the question, **including a phone number** (800-373-7600 parses as numbers). So
the refusal template has no digits and says "contact us" in words.

## R7. Links and URLs

When the question asks for a URL, give the **current tier A/B page** in the chosen snapshot,
never a legacy `info.dupaco.com/*` link or a moved page.
(CD rates → `dupaco.com/personal/savings-account`, not `info.dupaco.com/certificate_account_rates`.
Locator → `dupaco.com/contact`, not `/locations/branch-hours`.)

## R8. Determinism

Same question, same `as_of` → byte-identical answer. Paraphrases should resolve to the same
fact key and so produce the same numbers. This means no randomness, stable sorting, and
caching any LLM call keyed on the normalised question.

---

## How the rules feed `conflicts()`

For every fact key, collect observations across **all snapshots and pages**. Report a conflict
when there are two or more distinct values:

- **within a snapshot**: e.g. 05 `/rates` 5.39% vs `/calculators/vehicle-affordability` 5.34%;
  Roth jumbo 4.00% vs Traditional jumbo 3.90% on `/personal/retirement`
  (check whether those are genuinely different products before reporting);
- **across snapshots**: e.g. 10-month jumbo 3.90% → 4.00%.

`resolution` = the value R1–R5 pick for the latest snapshot. `reason` names the rule that
decided it ("tier-A rate sheet beats calculator effective 1/1/2026", "newer snapshot
2026-09-28"). Keep precision up: only report keys where both sides really share the same
fact key, not tier or metric differences.

---

## Decision procedure (what the code does)

```
answer(q, as_of):
  snap   = R1(as_of)
  key    = parse q → fact key (+ which metric, which tier)
  obs    = observations matching key in snap
  if none (or only D/E/X for a rate) → R6 refuse
  winner = max(obs, by (authority tier [R2/R2b], printed date [R3], member-count tiebreak [R3b]))
  if expired → R5 phrasing
  text   = one value (or the named tier set), metric-labelled, + source url of winner
  conflict_note = if obs had other values: "X on <page> is stale because <rule>"
```
