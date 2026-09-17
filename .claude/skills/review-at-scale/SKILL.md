---
name: review-at-scale
description: Run a broad or multi-agent code review without overspending — scope it, quote it in the unit the user is actually billed in, cap the fan-out, pick a model per job, and verify every finding before reporting it. Use when asked for a deeper or wider review than one pass, or before spawning subagents to review code.
---

# Reviewing at scale

A seven-agent review of this repo's security and orchestration core on 2026-09-16
found two real criticals. It also cost far more than it needed to, and three of its
findings did not survive contact with the code. Both halves are the lesson.

## Quote it before starting, in the right unit

This is the step that was skipped, and it was skipped *after being asked for*.

The user asked, in as many words, **"what will ultra review cost?"** The answer given
was for `/code-review ultra` — $5-25, with three free runs. Three alternatives were
then offered, **none of them priced**, along with the claim that the $5-25 "does not
apply" because they draw on session usage. That reads as *cheaper*. Seven parallel
Opus agents are not cheaper than a thing with three free runs.

- **Price the option you end up recommending**, not only the one named. Proposing an
  alternative moves the cost question; it does not retire it.
- **On a Max subscription there is no per-token bill.** Dollars are the wrong unit —
  `/usage` shows API-equivalent value, not money. What a big run actually spends is
  the 5-hour and weekly windows, so the useful sentence is "this will take a real bite
  out of your window", not "$25".
- **If a figure is genuinely unknown, say it is unknown.** A comparison with nothing
  behind it is worse than declining to compare.

## Scope before agents

Decide what is being reviewed first, and say how big it is. The 2026-09-16 run covered
the security and orchestration core plus Terraform — 4,565 lines — which was the right
call: a whole-codebase review is mostly scrapers, and scrapers are verified against
live vendor sites rather than by reading them.

Good scopes here are the things a scraper cannot verify: `src/auth/`, `src/scrapers/
netguard.py`, `src/scrapers/service.py`, `src/web/router.py`, `infra/`.

## Cap the fan-out

**Three or four agents with wide scopes, not seven with narrow ones.** Seven ran; the
two criticals they found (a login throttle that put every visitor in one bucket, and
an unchecked rendered-page redirect) would have surfaced from a wider split. Narrow
scopes also produce duplicate findings that each cost a full agent to generate.

## Pick the model per job

The Agent tool takes a `model` parameter. Use it.

| Job | Model |
|---|---|
| Searching, indexing, grep/jq, locating files | Haiku or Sonnet |
| Reading a diff for correctness, judging severity | Opus |

The transcript miner on 2026-09-16 was pure indexing and ran ~132k tokens on Opus for
no reason. Reserve the expensive model for work that turns on judgement.

**Never spawn an agent to investigate a cost concern.**

## Verify every finding before reporting it

A finding is a claim. Three from this run did not survive:

- **The proposed SSRF fix was refuted by experiment.** The design was to intercept the
  redirect in a `page.route` handler. Playwright does not re-invoke route handlers for
  redirect targets, and `route.fetch(max_redirects=0)` + `route.fulfill(response=...)`
  still does not re-enter the handler. The working fix reads
  `response.request.redirected_from` after `page.goto` and walks the chain.
- **The proposed throttle fix was actively wrong.** Replacing
  `--forwarded-allow-ips "*"` with the VPC CIDR alone stops uvicorn's reverse walk at
  CloudFront's egress address, putting *every* visitor in one shared throttle bucket —
  the same bug wearing a different hat. It needs the VPC CIDR **plus** CloudFront's
  origin-facing ranges.
- **A reproduction took the wrong code path.** See `scraper-batch` step 4.

So: reproduce the failure, or read the code path end to end, before it goes in a
report. A confident review that ships two wrong fixes costs more than a slower one.

## What to compare against

`/code-review ultra` is user-triggered and billed separately; it cannot be launched
from inside a session. When it is a candidate, say what it costs **and** what the
alternative costs, and let the user choose with both numbers visible.
