# 🛠️ Programmatic Skills Catalog (SKILLS.md)

This catalog details every programmatic skill, management command, utility service, and agent tool available in the **Book Trailer Lead Finder** application. Autonomous agents and human operators can execute these skills to ingest, crawl, verify, enrich, and export children's book author leads.

---

## 📋 Comprehensive Skills Matrix

| Skill Name | Invocation Command / Service | Purpose | Key Flags & Options | Output Type |
| :--- | :--- | :--- | :--- | :--- |
| **Excel Ingestion** | `python manage.py import_excel_leads` | Ingests production Excel workbooks with column shift safeguards | `<file_path>`, `--dry-run` | DB Records |
| **CSV Seeding** | `python manage.py import_books_csv` | Ingests raw CSV book seed lists | `<file_path>`, `--batch-size` | DB Records |
| **Demo Seeder** | `python manage.py seed_demo` | Generates realistic mock picture book leads | N/A | DB Records |
| **Keyword Discovery** | `python manage.py run_lead_research` | Single-batch keyword research pipeline | `--keyword`, `--max-books`, `--provider` | DB Records |
| **Bulk Discovery** | `python manage.py run_bulk_lead_research` | Multi-batch looping research to reach quota | `--target-leads`, `--batch-size`, `--output` | CSV & DB |
| **BookLife Scraper**| `python manage.py run_booklife_research` | Category scraping from PW BookLife index | `--category`, `--age-filter`, `--max-books` | DB Records |
| **Site Harvester** | `python manage.py harvest_author_site_leads`| Direct author website contact crawler | `--limit`, `--sleep` | DB Records |
| **Tavily Lookup** | `python manage.py pull_tavily_validated_leads` | Search author pages via Tavily API | `--target-leads`, `--output` | CSV & DB |
| **School Kit Scraper**| `python manage.py scrape_author_visit_leads` | Mines school visit and speaker kit pages | `--target-leads`, `--output`, `--sleep` | CSV File |
| **School Batch Runner**| `python manage.py scrape_author_visit_batches`| Runs author visit crawler across multiple queries| `--batch-size`, `--sleep` | CSV File |
| **Blog Harvester** | `python manage.py scrape_blog_book_leads` | Crawls children's book blogs & awards | `--max-posts`, `--category` | DB Records |
| **Scrapy Spiders** | `python manage.py scrape_scrapy_author_batches`| High-throughput concurrent Scrapy crawler | `--batch-size`, `--concurrency` | DB Records |
| **ASIN Repair** | `python manage.py enrich_existing_leads` | Backfills missing metadata & repairs names | `--asin`, `--dry-run`, `--force` | DB Records |
| **Catalog Sanitize**| `python manage.py sanitize_contact_sources` | Purges bookstore/catalog false positives | N/A | DB Clean |
| **Reverify Contacts**| `python manage.py reverify_contacts` | Re-runs verification on candidate contacts | `--all`, `--limit` | DB Records |
| **Stale Reverify** | `python manage.py reverify_stale_contacts` | Re-audits contacts older than $N$ days | `--days`, `--batch-size` | DB Records |
| **Scheduler Daemon**| `python manage.py run_scheduler_loop` | Executes recurring research hunts | `--daemon`, `--check-interval` | Daemon Worker|
| **Superadmin Setup**| `python manage.py bootstrap_superadmin` | Bootstraps default admin/manager/sales accounts| `--username`, `--email` | DB Users |
| **Export All CSV** | `python manage.py export_leads_csv` | Exports all pipeline leads to CSV | `--output` | CSV File |
| **Export Validated**| `python manage.py export_validated_author_leads`| Exports leads with verified author websites | `--output` | CSV File |
| **Export Contactable**| `python manage.py export_contactable_leads_csv`| Exports leads with verified email or phone | `--output` | CSV File |
| **Export Best Hot** | `python manage.py export_best_animation_leads` | Exports hot leads with no existing trailer | `--output` | CSV File |
| **ISBN Analyzer** | `leadfinder.services.isbn_intelligence` | Checksum validation and ASIN conversion | Programmatic Python API | Dict / JSON |
| **Barcode Maker** | `leadfinder.views.isbn_barcode` | Generates vector EAN-13 SVG barcode | HTTP GET Endpoint | SVG Image |
| **Groq Synthesizer**| `leadfinder.services.groq_service` | Formulates AI sales briefs and pitch hooks | Programmatic Python API | Dict / Brief |

---

## 1. Data Ingestion Skills

### `import_excel_leads`
* **Agent Role:** Scout / Coordinator
* **Description:** Ingests external Excel workbooks (`.xlsx`, `.xlsm`). Features automatic detection of shifted author/phone columns, publication date extraction, and lead deduplication against existing ASINs.
* **CLI Syntax:**
  ```powershell
  python manage.py import_excel_leads <file_path> [--dry-run]
  ```
* **Parameters:**
  * `<file_path>` *(Required)*: Path to `.xlsx` file (e.g. `"E:\yt-video\leads data.xlsx"`).
  * `--dry-run` *(Optional)*: Previews changes and stats without writing to database.
* **Input Contract:** Multi-column Excel worksheet with standard or client headers.
* **Output Contract:** Updates `Book`, `AuthorProfile`, `Lead`, `ContactCandidate`, `Evidence`, and `ResearchRun` models.

---

### `import_books_csv`
* **Agent Role:** Scout
* **Description:** Ingests standard CSV book catalogs containing book titles and author names.
* **CLI Syntax:**
  ```powershell
  python manage.py import_books_csv <file_path> [--batch-size 100]
  ```

---

## 2. Discovery Skills

### `run_lead_research`
* **Agent Role:** Scout / Harvester / Auditor
* **Description:** Initiates the standard single-batch discovery and enrichment pipeline.
* **CLI Syntax:**
  ```powershell
  python manage.py run_lead_research --keyword <query> [options]
  ```
* **Parameters:**
  * `--keyword` *(Required)*: Search query string (e.g. `"kids bedtime story picture book"`).
  * `--max-books` *(Default: `25`)*: Maximum book listing URLs to discover.
  * `--provider` *(Default: `ddgs`)*: Search provider (`ddgs`, `tavily`, `brave`, `google_books`).
  * `--require-public-email`: Excludes leads that lack a public email.
  * `--no-video-search`: Skips YouTube and Vimeo trailer scanning.
  * `--no-ai`: Uses offline deterministic templates instead of Groq LLM.

---

### `run_bulk_lead_research`
* **Agent Role:** Scout / Coordinator
* **Description:** Loops through keyword suggestion groups until a target quota of qualified leads is reached.
* **CLI Syntax:**
  ```powershell
  python manage.py run_bulk_lead_research --target-leads 700 --batch-size 25 --provider tavily --output data/leads_700.csv
  ```

---

### `run_booklife_research`
* **Agent Role:** Scout
* **Description:** Discovers independent authors through Publishers Weekly BookLife category listings.
* **CLI Syntax:**
  ```powershell
  python manage.py run_booklife_research --category fiction-romance --age-filter children-young-adult --max-books 50
  ```

---

## 3. Web Scraping & Harvesting Skills

### `harvest_author_site_leads`
* **Agent Role:** Harvester
* **Description:** Direct crawler that visits known author websites, extracting emails, phones, and representation contacts.
* **CLI Syntax:**
  ```powershell
  python manage.py harvest_author_site_leads [--limit 50] [--sleep 0.5]
  ```

---

### `pull_tavily_validated_leads`
* **Agent Role:** Harvester
* **Description:** Queries Tavily Search to identify official author websites and extracts contact coordinates.
* **CLI Syntax:**
  ```powershell
  python manage.py pull_tavily_validated_leads --target-leads 200 --output data/tavily_leads.csv
  ```

---

### `scrape_author_visit_leads`
* **Agent Role:** Harvester
* **Description:** Targets school presentation, author booking, and media kit pages to pull direct booking emails.
* **CLI Syntax:**
  ```powershell
  python manage.py scrape_author_visit_leads --target-leads 400 --output data/school_visits.csv --sleep 0.2
  ```

---

## 4. Verification & Enrichment Skills

### `sanitize_contact_sources`
* **Agent Role:** Auditor
* **Description:** Scans all contact candidate records and removes bookstore and catalog false positives (Open Library, Goodreads, MIT Press).
* **CLI Syntax:**
  ```powershell
  python manage.py sanitize_contact_sources
  ```

---

### `reverify_contacts`
* **Agent Role:** Auditor
* **Description:** Re-runs verification algorithms (syntax, domain alignment, and MX records) against existing contact candidates.
* **CLI Syntax:**
  ```powershell
  python manage.py reverify_contacts [--all] [--limit 100]
  ```

---

### `enrich_existing_leads`
* **Agent Role:** Harvester / Auditor
* **Description:** Repairs records with missing author names, scrapes Amazon ASIN profile data, and recalibrates scores.
* **CLI Syntax:**
  ```powershell
  python manage.py enrich_existing_leads --asin B0OCTSHAR5 --force
  ```

---

## 5. Scheduler & Delivery Skills

### `run_scheduler_loop`
* **Agent Role:** Coordinator
* **Description:** Runs the background worker daemon executing recurring research hunts.
* **CLI Syntax:**
  ```powershell
  python manage.py run_scheduler_loop --daemon --check-interval 60
  ```

---

### `export_best_animation_leads`
* **Agent Role:** Coordinator
* **Description:** Filters and exports top-tier hot leads (Score $\ge 75$, verified email, no existing trailer).
* **CLI Syntax:**
  ```powershell
  python manage.py export_best_animation_leads --output data/hot_leads.csv
  ```

---

## 6. Programmatic Python Service Skills

### `validate_isbn(identifier: str) -> dict`
* **Module:** `leadfinder.services.isbn_intelligence`
* **Function:** Validates ISBN-10, ISBN-13, and ASIN checksums. Returns canonical forms, barcode URLs, and validation states.

### `generate_ai_sales_brief(lead: Lead) -> SalesAgentBrief`
* **Module:** `leadfinder.services.groq_service`
* **Function:** Queries Groq LLM (or deterministic fallback) with book summary and genre to generate sales pitch hooks and custom first-line emails.
