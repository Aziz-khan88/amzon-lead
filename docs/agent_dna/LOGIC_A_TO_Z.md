# Logic A To Z

This document maps the full system logic from input to delivery.

## A. Accept Input

Inputs can come from:

- Keyword search run.
- Bulk keyword run.
- BookLife category run.
- CSV import.
- ISBN/ASIN batch.
- Existing records needing enrichment.

## B. Build ResearchRun

Create `ResearchRun` with:

- `keyword`
- `source_provider`
- `marketplace`
- `max_books`
- `settings_json`
- initial `status`

Settings include video search, AI extraction, contact requirements, Amazon URL requirement, social-only behavior, and location preference.

## C. Check Cancellation

Long-running pipeline steps should check whether the run has been canceled. Saved records remain available even if later steps stop.

## D. Discover Candidate Books

Discovery uses the selected source:

- Search providers for keyword runs.
- BookLife provider for category runs.
- CSV row parser for imports.
- ISBN/ASIN lookup for manual batches.
- Existing database rows for enrichment backfills.

## E. Extract Book Metadata

Normalize:

- title
- author
- illustrator
- ASIN/ISBN
- Amazon URL
- category
- publisher
- publication date
- rating/review metadata
- cover image
- source URL/title/snippet

## F. Filter Unsafe Sources

Reject or avoid:

- private networks and unsafe URLs
- login walls
- catalogs posing as contacts
- bookstore support pages
- unrelated retailer records
- bad author names
- noisy title fragments

## G. Generate Normalized Keys

Use title, author, and ASIN where available to build deterministic book and author keys for dedupe.

## H. Hydrate Book Records

Create or update `Book` records connected to the current `ResearchRun`.

## I. Identify Author Context

For each book, identify likely author-owned or authorized channels:

- official author site
- publisher page
- contact page
- agent page
- publicist page
- social profile
- Amazon author page

## J. Join Evidence

Create `Evidence` rows for source-backed fields. Important evidence fields include source URL, source title, source snippet, field name, field value, confidence, and evidence type.

## K. Keep Public Fetching Safe

When crawling pages:

- respect URL safety checks
- respect robots where configured
- use timeouts
- avoid blocked hosts
- avoid deep or aggressive crawling
- prefer candidate contact/about/media paths

## L. Locate Contact Signals

Extract:

- public email
- public phone
- representation email
- publicist email
- contact page
- publisher page
- social links
- location

## M. Match Identity

Compare:

- author name tokens
- domain signals
- page title
- snippets
- text body
- profile names
- book mentions

Weak identity match should lower confidence or trigger review warnings.

## N. Normalize Contact Data

Clean emails, phones, URLs, and names. Remove obvious bad values and generic non-author contacts.

## O. Observe Video Evidence

Search public sources for:

- animated book trailer
- book trailer
- read-aloud only
- unrelated videos
- unclear results
- no public video found in searched sources

## P. Protect Safe Wording

Use safe video wording. Do not say an author has no video. The correct meaning is only that searched public sources did not reveal one.

## Q. Qualify Book Fit

Classify whether the book appears to be:

- children's
- picture book
- illustrated book
- adjacent but uncertain
- non-fit

AI may help when configured; deterministic fallback should still work.

## R. Reconcile Lead

Merge discovered contact data into a coherent `Lead`. Resolve conflicts using confidence, source type, and identity alignment.

## S. Score Lead

Score considers:

- book fit
- Amazon URL or ASIN
- contactability
- website/social/contact evidence
- video opportunity
- identity confidence
- extraction confidence
- warnings
- missing data
- review/do-not-contact state

## T. Tier Lead

Assign:

- hot
- warm
- cold
- rejected

Hot leads require strong score, contact channel, book fit, and acceptable video status.

## U. Update Sales Brief

Populate:

- sales agent summary
- suggested pitch angle
- suggested first line
- what to say
- what not to say
- next best action

## V. Validate Review State

Default review status should be `needs_review`. Operators can approve, reject, or mark do-not-contact.

## W. Write Logs

Persist search query logs, run status, error messages, audit events, warnings, and evidence so debugging is possible.

## X. Export Rows

Exports should include:

- book title
- author
- ASIN/Amazon URL
- contact details
- contact source
- video status
- score/tier
- review status
- evidence URLs
- warnings
- sales brief fields

## Y. Yield Operator Feedback

UI should show:

- run counts and status
- failed/canceled/completed state
- latest runs
- lead filters and queue counts
- action buttons for open, retry, export, approve, reject, do-not-contact

## Z. Zero-Trust Final Rule

Do not treat scraped or AI-produced data as final truth. Every important field should be inspectable, source-backed where possible, and reviewable by a human before outreach.

## Pseudocode

```text
create run
mark run running
for each discovered book candidate:
    normalize book
    dedupe book
    store book
    find author/contact/video evidence
    validate identity and contact source
    classify book and video fit
    reconcile lead
    score lead
    write sales brief
    write evidence and logs
if not canceled:
    mark run completed
on error:
    mark run failed with message
```
