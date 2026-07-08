# Lead Finder Agent Skills

This document outlines the programmatic skills (management commands, utilities, and services) available in this repository. These skills can be invoked to discover, scrape, verify, and export high-conversion children's book author leads.

---

## 🛠️ Core Skills Matrix

| Skill Group | Management Command | Purpose | Essential Options | Output Type |
| :--- | :--- | :--- | :--- | :--- |
| **Discovery** | `run_lead_research` | Keyword-based lead research pipeline | `--keyword`, `--max-books`, `--provider` | DB Entries |
| **Discovery** | `run_bulk_lead_research` | Automated bulk run loops | `--target-leads`, `--batch-size`, `--provider` | CSV & DB |
| **Discovery** | `run_booklife_research` | BookLife category discovery | `--category`, `--age-filter`, `--max-books` | DB Entries |
| **Scraping** | `scrape_author_visit_leads` | Scrape school visits & match ASIN | `--target-leads`, `--output`, `--sleep` | CSV |
| **Scraping** | `pull_tavily_validated_leads` | Search author pages, extract info, match ASIN | `--target-leads`, `--output`, `--sleep` | CSV |
| **Enrichment** | `enrich_existing_leads` | Fix missing details & Amazon profile fetch | `--asin`, `--dry-run`, `--force` | DB Update |
| **Sanitization** | `sanitize_contact_sources` | Clean up invalid/catalog contact data | N/A | DB Clean |
| **Data Ops** | `import_books_csv` | Seed database with book CSV | `[csv_path]` | DB Entries |
| **Data Ops** | `seed_demo` | Seed mock picture book records | N/A | DB Seed |
| **Export** | `export_leads_csv` | Export all pipeline leads to CSV | N/A | CSV |
| **Export** | `export_validated_author_leads` | Export verified author-site leads | N/A | CSV |
| **Export** | `export_contactable_leads_csv` | Export leads with emails/phones | N/A | CSV |
| **Export** | `export_best_animation_leads` | Export hot fit + no video leads | N/A | CSV |

---

## 🔍 Detailed Skill Reference

### 1. Keyword Lead Research (`run_lead_research`)
* **Description:** Initiates the standard single-batch discovery and enrichment pipeline.
* **Execution:**
  ```powershell
  python manage.py run_lead_research --keyword "children picture book" --max-books 25 --provider ddgs
  ```
* **Parameters:**
  * `--keyword` (Required): Search query to discover books (e.g. `"kids bedtime story"`).
  * `--max-books` (Default: `25`): Limit of book URLs to discover.
  * `--provider` (Choices: `ddgs`, `tavily`, `brave`, `amazon_creators`, `google_books`): Search indexing provider.
  * `--require-public-email`: Skips leads without a public email address.
  * `--no-video-search`: Disables scanning YouTube/Vimeo for trailers.
  * `--no-ai`: Bypasses Groq-based content classification, applying deterministic fallbacks.

---

### 2. Bulk Multi-Batch Pipeline (`run_bulk_lead_research`)
* **Description:** Continuously runs research across multiple keyword suggestion groups until a target lead threshold is reached, then automatically exports the result.
* **Execution:**
  ```powershell
  python manage.py run_bulk_lead_research --target-leads 700 --batch-size 25 --provider tavily --output data/book_trailer_leads_700.csv
  ```
* **Parameters:**
  * `--target-leads` (Default: `700`): Limit threshold for final qualified leads.
  * `--batch-size` (Default: `25`): Number of books retrieved per keyword query.
  * `--provider` (Default: `tavily`): Indexing search provider.
  * `--output`: Absolute or relative path to save the final CSV.
  * `--allow-missing-email` / `--allow-missing-phone` / `--allow-missing-amazon-url`: Relaxes qualification filters.

---

### 3. BookLife Category Crawler (`run_booklife_research`)
* **Description:** Discovers books directly from the PW BookLife category page listings and inserts them into the enrichment pipeline.
* **Execution:**
  ```powershell
  python manage.py run_booklife_research --category fiction-romance --age-filter children-young-adult --max-books 25
  ```
* **Parameters:**
  * `--category` (Required): BookLife category slugs (e.g. `fiction-mystery-thriller`, `comics-graphic-novels`).
  * `--age-filter`: Slug filtering (e.g. `children-young-adult`, `adult`).
  * `--max-books`: Maximum books to harvest from list views.

> [!NOTE]
> Since PW BookLife disallows generic web crawlers, this runner executes search-index fallbacks unless `BOOKLIFE_DIRECT_FETCH_ALLOWED=1` is enabled in the environment.

---

### 4. Author School Visit Scraper (`scrape_author_visit_leads`)
* **Description:** Targets pages containing author booking, school presentations, or media kit details, crawls them to pull contact coordinates, and matches them to active Amazon children's books.
* **Execution:**
  ```powershell
  python manage.py scrape_author_visit_leads --target-leads 400 --output data/scraped_valid_children_author_leads_400.csv --sleep 0.15
  ```
* **Parameters:**
  * `--target-leads`: Number of successful leads to compile.
  * `--output`: Output destination for the custom CSV file.
  * `--max-results` (Default: `20`): Tavily search results per query.
  * `--max-pages-per-site` (Default: `4`): Crawling depth per author website.

---

### 5. Validate & Enrich Existing Records (`enrich_existing_leads`)
* **Description:** Repairs records with invalid or missing author names, scrapes Amazon ASIN profiles, refreshes identity scores, and resets manual status.
* **Execution:**
  ```powershell
  python manage.py enrich_existing_leads --dry-run
  python manage.py enrich_existing_leads --asin B0OCTSHAR5 --force
  ```
* **Parameters:**
  * `--asin`: Limit enrichment to a specific book ASIN.
  * `--dry-run`: Scrapes and previews changes without saving them.
  * `--force`: Forcefully overwrites details even if the author name is already valid.

---

### 6. Specialized Exporters
* **Description:** Generates targeted lists of high-priority leads with custom column configurations.
* **Commands:**
  * `export_leads_csv`: Standard pipeline export.
  * `export_validated_author_leads`: Exports only leads with confirmed author-site ownership.
  * `export_contactable_leads_csv`: Exports leads containing at least one valid public contact channel.
  * `export_best_animation_leads`: Filter leads to only the highest scoring (tier >= Hot) picture books with `no_public_video_found` status.
