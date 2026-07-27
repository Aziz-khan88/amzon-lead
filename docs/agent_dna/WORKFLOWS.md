# Workflows

## Master Pipeline

```text
Operator input
  -> Scout discovery
  -> Book records
  -> Harvester enrichment
  -> Candidate lead/contact/video evidence
  -> Auditor validation
  -> Scored lead
  -> Copywriter sales brief
  -> Coordinator review/export
```

## Workflow 1: Keyword Research Run

1. Operator opens `/runs/new/`.
2. Operator enters a keyword or selects a suggested keyword.
3. `ResearchRunForm` validates keyword and run settings.
4. `views.run_new` creates a `ResearchRun`.
5. `_start_research_pipeline` runs `run_research_pipeline` in the background.
6. Scout builds discovery queries.
7. Search provider returns candidate pages.
8. Amazon URLs, ASINs, titles, and authors are parsed from allowed public sources.
9. Books are deduped and stored.
10. Harvester processes each book.
11. Auditor validates identity/contact/video/book fit.
12. Copywriter creates sales brief fields.
13. Coordinator exposes results in run detail, leads list, and exports.

## Workflow 2: BookLife Run

1. Operator opens `/runs/booklife/`.
2. Operator selects categories, age fit, limit, enrichment source, and pipeline toggles.
3. The app creates a `ResearchRun` with `source_provider="booklife"`.
4. BookLife provider gathers category/project candidates.
5. If direct fetch is not allowed, search-index snippets are used as fallback.
6. Candidate books enter the same enrichment and audit pipeline as keyword runs.

## Workflow 3: CSV Import

1. Operator uploads a CSV at `/import-csv/` or runs `import_books_csv`.
2. Accepted columns are normalized into book rows.
3. A `ResearchRun` is created with `source_provider="csv"`.
4. Imported books are stored with source metadata.
5. The pipeline enriches each imported book.
6. Results are available through runs, leads, and exports.

## Workflow 4: ISBN/ASIN Search

1. Operator opens `/isbn-search/`.
2. Operator enters ASINs, ISBNs, Amazon URLs, or mixed text.
3. The app normalizes identifiers and checks existing records.
4. ISBN checksums must agree across the built-in verifier, `isbnlib`, and `pyisbn`; equivalent ISBN-10/13 forms are deduplicated.
5. Exact Open Library and Google Books matches are reconciled field by field, cached, and stored with source evidence. B0-prefixed ASINs remain syntax-only until public evidence is found.
6. Missing or conflicting records use indexed public search fallback and remain flagged for review.
7. A manual run is created for new batch work.
8. Book records are enriched into leads.

## Workflow 5: Lead Review

1. Reviewer opens `/leads/`.
2. Reviewer filters by score, tier, contactability, review status, video status, or source fields.
3. Reviewer opens lead detail for evidence.
4. Reviewer checks source URLs, audit report, sales brief, and warnings.
5. Reviewer marks lead approved, rejected, do-not-contact, or leaves as needs-review.
6. Do-not-contact clamps the lead out of outreach-ready export logic.

## Workflow 6: Export

1. Coordinator filters the lead queryset.
2. Export endpoint or CLI command serializes rows.
3. Export includes book, author, contact, confidence, video status, source URLs, warnings, and sales context.
4. Outreach team receives CSV/XLSX.

## Workflow 7: Failed Or Canceled Runs

1. Operator sees failed/canceled state in `/runs/`.
2. Run detail exposes logs and errors.
3. Operator can retry failed or canceled runs.
4. Retry creates a fresh `ResearchRun` with copied settings.
5. Existing saved work remains intact.

## Agent Handoffs

### Scout To Harvester

Pass:

- Book title
- Author or illustrator
- ASIN/ISBN
- Amazon URL
- Source provider
- Search result source metadata

### Harvester To Auditor

Pass:

- Candidate website/contact/social URLs
- Public email/phone candidates
- Page title/snippet/text evidence
- Video search results
- Extraction confidence

### Auditor To Copywriter

Pass:

- Book fit
- Contact fit
- Identity confidence
- Video status
- Warnings
- Missing data
- Source evidence

### Copywriter To Coordinator

Pass:

- Sales summary
- Suggested pitch angle
- Suggested first line
- What to say
- What not to say
- Next best action

## Operational Guardrails

- Keep every run restartable or retryable.
- Never delete evidence silently.
- Never overwrite do-not-contact without explicit operator action.
- Avoid claiming unavailable facts.
- Keep public source links visible.
- Prefer review queues over automatic outreach.
