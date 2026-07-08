# Skill Catalog

This catalog maps product capabilities to the agent roles and code surfaces that implement them.

## Agent Roles

| Agent | Purpose | Primary Output |
| --- | --- | --- |
| Scout | Discover book candidates | `Book` records |
| Harvester | Enrich author/contact/video data | `AuthorProfile`, `Lead`, `Evidence` |
| Auditor | Validate identity, contact, book, and video quality | confidence, warnings, review status |
| Copywriter | Generate sales brief and pitch guidance | pitch fields on `Lead` |
| Coordinator | Filter, package, export, and manage delivery | CSV/XLSX sheets |

## Discovery Skills

| Skill | Interface | Core Code | Notes |
| --- | --- | --- | --- |
| Keyword research | UI `/runs/new/`, CLI `run_lead_research` | `services/pipeline/run_research.py` | Creates `ResearchRun`, searches providers, seeds books, enriches leads. |
| Bulk keyword research | CLI `run_bulk_lead_research` | `management/commands/run_bulk_lead_research.py` | Repeats research until target qualified lead count or query exhaustion. |
| BookLife discovery | UI `/runs/booklife/`, CLI `run_booklife_research` | `services/booklife/provider.py` | Uses BookLife categories and search-index fallback unless direct fetch is allowed. |
| CSV import | UI `/import-csv/`, CLI `import_books_csv` | `views.import_books_from_rows` | Imports known book data and starts enrichment. |
| ISBN/ASIN search | UI `/isbn-search/` | `services/books/isbn_keyword_lookup.py`, `views.isbn_search` | Supports manual or batch lookups and creates manual runs. |

## Search Provider Skills

| Provider | Code | Role |
| --- | --- | --- |
| DDGS | `services/search/ddgs_provider.py` | Default no-key web search. |
| DDG HTML | `services/search/ddgs_html_provider.py` | HTML fallback search path. |
| Tavily | `services/search/tavily_provider.py` | Paid/structured web search when configured. |
| Brave | `services/search/brave_provider.py` | Paid web search when configured. |
| Google CSE | `services/search/google_provider.py` | Google search when configured. |
| Cached provider | `services/search/cache.py` | Avoids repeat search work during short windows. |
| Video search | `services/search/video_provider.py` | YouTube API or fallback video evidence search. |

## Book Data Skills

| Skill | Code | Output |
| --- | --- | --- |
| Amazon URL parsing | `services/amazon/amazon_url_parser.py` | ASIN and normalized Amazon URL. |
| Amazon search-result metadata | `services/amazon/amazon_scraper.py` | Metadata from allowed public result paths, not product-page scraping. |
| Amazon Creators provider | `services/amazon/amazon_creators_provider.py` | Optional provider placeholder/integration. |
| Open Library lookup | `services/books/open_library_provider.py` | Book metadata for ISBN workflows. |
| Google Books lookup | `services/books/google_books_provider.py` | Book metadata when configured. |
| Seed CSV reader | `services/amazon/seed_provider.py` | Local seed rows. |

## Enrichment Skills

| Skill | Interface | Code | Notes |
| --- | --- | --- | --- |
| Process book | Pipeline | `services/pipeline/process_book.py` | Converts book candidates into enriched leads. |
| Safe fetching | Service | `services/crawl/safe_fetch.py` | Applies public URL and timeout protections. |
| Robots checks | Service | `services/crawl/robots.py` | Checks fetch permission. |
| Contact extraction | Service | `services/crawl/contact_regex.py`, `services/ai/extract_contact.py` | Extracts public emails, phones, and contact signals. |
| Link extraction | Service | `services/crawl/extract_links.py` | Identifies author, contact, social, publisher, and evidence URLs. |
| Text extraction | Service | `services/crawl/extract_text.py` | Produces crawlable text for audit and AI extraction. |
| Existing lead enrichment | CLI `enrich_existing_leads` | management command | Backfills or enriches existing records. |

## Audit And Validation Skills

| Skill | Code | Rule |
| --- | --- | --- |
| Source audit | `services/pipeline/source_audit.py` | Tracks source fit and evidence trust. |
| Quality gate | `services/pipeline/quality_gate.py` | Blocks or warns on low-quality candidates. |
| Lead validator | `services/pipeline/lead_validator.py` | Validates contactability and completeness. |
| MX validator | `services/pipeline/mx_validator.py` | Checks domain/mail viability where appropriate. |
| Dedupe | `services/pipeline/dedupe.py` | Prevents duplicate books/leads. |
| Contact reconciliation | `services/ai/reconcile_lead.py` | Reconciles conflicting extracted contact data. |
| Video classification | `services/ai/classify_video.py` | Distinguishes trailer, animated video, read-aloud, unclear, and not found. |
| Book classification | `services/ai/classify_book.py` | Detects children's/picture-book fit. |
| Sanitization | CLI `sanitize_contact_sources` | Removes or marks bad catalog/contact sources. |

## Scoring And Copy Skills

| Skill | Code | Output |
| --- | --- | --- |
| Lead score | `services/scoring/lead_score.py` | `lead_score`, `lead_tier`, warnings, missing data. |
| Sales brief | `services/ai/summarize_sales_brief.py` | sales summary, pitch angle, first line, what to say, what not to say. |
| Groq client | `services/ai/groq_client.py` | Structured AI completion when configured. |
| Prompts and schemas | `services/ai/prompts.py`, `services/ai/schemas.py` | Structured task contracts. |

## Delivery Skills

| Skill | Interface | Code | Output |
| --- | --- | --- | --- |
| Export CSV | UI `/export/leads.csv`, CLI `export_leads_csv` | `services/export/csv_export.py` | CSV lead sheet. |
| Export XLSX | UI `/export/leads.xlsx` | `services/export/csv_export.py` | Excel lead sheet. |
| Export validated authors | CLI `export_validated_author_leads` | management command | Review-ready author leads. |
| Export contactable leads | CLI `export_contactable_leads_csv` | management command | Contactable rows. |
| Export best animation leads | CLI `export_best_animation_leads` | management command | Prioritized animation-fit leads. |

## UI Skills

| Screen | Route | Purpose |
| --- | --- | --- |
| Dashboard | `/dashboard/` | Monitor totals, workflow, queues, and latest runs. |
| Leads | `/leads/` | Filter, review, approve, reject, and open leads. |
| Lead detail | `/leads/<uuid>/` | Inspect evidence, audit status, and sales context. |
| Runs | `/runs/` | Track run status, results, retry, and open runs. |
| Run detail | `/runs/<uuid>/` | Inspect run logs, books, leads, and agent status. |
| New run | `/runs/new/` | Launch keyword discovery. |
| BookLife run | `/runs/booklife/` | Launch BookLife category discovery. |
| Import CSV | `/import-csv/` | Upload seed files. |
| ISBN Search | `/isbn-search/` | Run ASIN/ISBN lookup batches. |

## Safety Skills

| Skill | Code | Purpose |
| --- | --- | --- |
| URL safety | `utils/url_safety.py` | Blocks unsafe/private URL fetches. |
| Normalization | `utils/normalize.py` | Cleans titles/authors and supports dedupe. |
| Source confidence | `utils/source_confidence.py` | Clamps and merges confidence values. |
| Cancellation | `services/pipeline/cancellation.py` | Allows run cancellation without corrupting saved work. |
