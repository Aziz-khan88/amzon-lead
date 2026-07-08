# Product DNA

## Identity

Book Trailer Lead Finder is an evidence-first lead qualification system for children's book trailer outreach. It is not a generic scraper. It is a research, enrichment, audit, scoring, and export tool.

## North Star

Deliver fewer, cleaner, better-supported leads that an outreach team can trust.

## Operating Principles

- Evidence first: keep source URLs and confidence close to every important claim.
- Public data only: use public professional/contact signals and respect source boundaries.
- Safe wording: avoid claims the system cannot prove.
- Human review by default: leads start in review-oriented states, not auto-approved.
- Precision over volume: reject noisy sources and weak contact matches.
- Deterministic fallback: API-enhanced flows should degrade gracefully when keys are missing.
- No hidden magic: preserve logs, warnings, missing data, and audit trails.

## Data Ethics

The product should only use public professional data suitable for business outreach. It must not infer private contact details, scrape private pages, or hide uncertainty from operators.

## Lead Quality DNA

A strong lead usually has:

- A children's, picture, illustrated, or adjacent book fit.
- A useful Amazon URL or ASIN when required.
- A contact path such as direct public email, agent email, publicist email, contact page, official website, or credible publisher channel.
- No public animated trailer or book trailer found in searched sources, or an unclear video state that still warrants review.
- Strong identity alignment between the author name, page content, domain, and extracted contact.
- Low mismatch risk and useful sales context.

## Rejection DNA

A weak or rejected lead often has:

- Retailer, catalog, library, or support desk contact sources.
- Unclear author identity.
- Non-children's-book fit.
- Existing trailer or animated video evidence when the outreach angle depends on trailer absence.
- No actionable contact channel.
- Do-not-contact state.

## Human Review Philosophy

The system should prepare the decision, not pretend to replace it. A reviewer should be able to answer:

- What book is this?
- Who is the author or official representative?
- Where did each contact detail come from?
- Why does this fit or not fit a trailer outreach campaign?
- What should the outreach person say, and what should they avoid saying?

## UI DNA

The UI should feel like a focused operations cockpit:

- Dark, dense, calm, and scannable.
- Teal for primary actions and active states.
- Yellow for review attention.
- Red for failed or blocked states.
- Compact cards and tables for repeated operator use.
- Source-backed details over marketing copy.

## Engineering DNA

- Keep logic testable and modular.
- Prefer provider interfaces and service modules over view-heavy logic.
- Keep exports deterministic.
- Store raw/source JSON when useful for audit and reprocessing.
- Avoid destructive cleanup unless explicitly requested.
- Keep compliance behavior close to the pipeline and tests.

## Success Statement

The product succeeds when operators can run repeatable research, reviewers can trust the evidence, and outreach teams receive clean lists with clear context and low mismatch risk.
