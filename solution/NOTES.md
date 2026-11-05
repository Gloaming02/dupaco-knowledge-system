# NOTES

> Draft. Update as the design firms up; reviewers read this.

## How it works
_TBD_: ingest → fact extraction → temporal store → retrieval → answer.

## How "current" is decided
Full rules with the real cases behind each one are in [`docs/RULES.md`](../docs/RULES.md). In short:

1. **Time first.** No `as_of` means the latest snapshot. With `as_of=D`, use the newest snapshot on or before D.
2. **Authority next.** Rate sheets (`/rates`, `/business-rates`) > product pages > reference
   pages > calculators and landing pages > blog and newsroom > legacy `info.dupaco.com`.
   Newsroom is still valid for events nobody else covers (e.g. a branch closure).
3. **Printed date breaks ties.** Use "effective as of", then publish date, then "updated". Never
   use the crawl date (every page is re-fetched each crawl). Company stats come from the newest
   press-release boilerplate, never a majority vote.
4. **Qualifiers make different facts.** Term, balance/loan tier, model-year band, rate vs APY,
   and personal/business/IRA are part of the fact's key. Different keys are never a conflict.
5. **Expired means expired.** Past end dates are reported as ended, not as current.
6. **Refuse honestly.** If the snapshot has no tier A–C evidence for the fact, say so and
   suggest contacting the credit union, with no numbers.

## Conflicts
_TBD_

## API keys / dependencies
None so far (standard library only). If an LLM is added, state the key and the model here.
