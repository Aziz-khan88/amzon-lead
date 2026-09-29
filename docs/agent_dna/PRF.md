# Product Requirements Framework

## Product

Book Trailer Lead Finder is a Django lead research system for finding children's book authors who may be a fit for animated book trailers, animated promo videos, or short social ads.

## Primary Users

- Research operators who run discovery jobs.
- Reviewers who qualify leads and inspect source evidence.
- Outreach teams who export clean lead sheets.
- Developers and agents who maintain discovery, enrichment, audit, scoring, and export logic.

## Core Problem

Outreach teams need high-quality children's book author leads, but raw search results are noisy. The system must separate real author opportunities from catalog pages, bookstore listings, mismatched contacts, existing trailer/video cases, and low-confidence scraped data.

## Product Promise

Find and qualify book trailer opportunities with evidence, confidence, review states, and exportable lead records.

## Must Do

- Discover book candidates from keyword search, BookLife categories, CSV imports, ISBN/ASIN batches, and supported book metadata providers.
- Store discovered books with title, author, ASIN, Amazon URL, source provider, and source evidence when available.
- Enrich books into leads by finding official author sites, contact pages, publisher pages, public social links, email signals, phone signals, locations, and video evidence.
- Audit identity alignment between author names, domains, page titles, snippets, and extracted contact data.
- Reject catalog, bookstore, library, retailer, and generic support contacts as author contact data.
- Classify video status without overstating absence of video.
- Score leads deterministically and assign tiers.
- Generate sales-agent-ready context and pitch guidance.
- Export production-ready CSV/XLSX lead sheets with source URLs, warnings, missing fields, and confidence.
- Preserve manual review states, do-not-contact state, retry flows, and run cancellation.

## Must Not Do

- Do not scrape Amazon product pages.
- Do not bypass CAPTCHA, Cloudflare, login walls, or rate limits.
- Do not scrape private or logged-in social platforms.
- Do not use leaked, private, people-search, or hidden contact databases.
- Do not auto-send outreach.
- Do not claim that an author has no video; use safe wording such as "No public video found in searched sources."
- Do not treat weak evidence as verified contact data.

## Key User Journeys

1. Operator creates a research run from `/runs/new/`.
2. Scout discovers books through keyword, BookLife, CSV, or ISBN inputs.
3. Harvester enriches books into author/contact/video candidates.
4. Auditor validates identity, contact fit, book fit, and video classification.
5. Copywriter generates sales brief fields and pitch guidance.
6. Coordinator filters, reviews, and exports qualified leads.

## Acceptance Criteria

- A run can be created from UI and CLI.
- Runs have visible status, counts, records, and retry/open actions.
- Leads show source-backed book/contact/video/evidence data.
- Filters support common operator review workflows.
- Exports include only the fields needed for outreach and review.
- Tests pass for core UI pages, scoring, contact extraction, provider behavior, and exports.

## Quality Metrics

- Contact precision: avoid mismatched, bookstore, catalog, and support desk contacts.
- Evidence coverage: important fields should include source URLs where possible.
- Review efficiency: reviewers can identify contactable, no-video, and high-score leads quickly.
- Compliance safety: safe wording and public-only data rules are maintained.
- Pipeline resilience: failed or canceled runs can be understood and retried.

## Current Product Surfaces

- `/dashboard/`: executive workbench and pipeline summary.
- `/leads/`: lead review, filters, and lead actions.
- `/runs/`: run history, status, retry/open controls.
- `/runs/new/`: keyword discovery run creation.
- `/runs/booklife/`: BookLife category runner.
- `/import-csv/`: Manual CSV/XLSX/XLSM lead import with header detection, preview, export-format round trip, and optional video/contact/AI checks.
- `/isbn-search/`: ASIN/ISBN batch lookup.
- `/export/leads.csv` and `/export/leads.xlsx`: lead delivery.
