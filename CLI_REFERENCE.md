# 💻 CLI Management Commands Reference

The **Book Trailer Lead Finder** platform includes 22 custom Django management commands providing complete command-line control over data ingestion, crawling, enrichment, verification, scheduling, and exports.

---

## 📋 Commands Categorized Matrix

| Category | Command | Primary Function | Output |
| :--- | :--- | :--- | :--- |
| **Ingestion** | `import_excel_leads` | Ingest external Excel workbooks with column-shift protection | DB Records |
| **Ingestion** | `import_books_csv` | Ingest standard CSV book seed files | DB Records |
| **Ingestion** | `seed_demo` | Populate database with realistic mock picture book leads | DB Records |
| **Discovery** | `run_lead_research` | Standard single-batch keyword discovery pipeline | DB Records |
| **Discovery** | `run_bulk_lead_research` | Automated multi-batch keyword discovery loop | CSV & DB |
| **Discovery** | `run_booklife_research` | Harvest indie books from PW BookLife categories | DB Records |
| **Scraping** | `harvest_author_site_leads` | Direct crawling of author websites for contact signals | DB Records |
| **Scraping** | `pull_tavily_validated_leads` | Tavily API search for author contact coordinates | CSV & DB |
| **Scraping** | `scrape_author_visit_leads` | Scrapes school visit and speaker kit pages | CSV |
| **Scraping** | `scrape_author_visit_batches` | Batch coordinator for school visit scrapers | CSV |
| **Scraping** | `scrape_blog_book_leads` | Harvests book recommendations from review blogs | DB Records |
| **Scraping** | `scrape_scrapy_author_batches`| High-concurrency Scrapy crawler integration | DB Records |
| **Enrichment** | `enrich_existing_leads` | Repairs records, backfills ASINs, refines author names | DB Records |
| **Verification**| `reverify_contacts` | Re-runs verification checks across contact candidates | DB Records |
| **Verification**| `reverify_stale_contacts` | Re-audits contacts older than configured threshold | DB Records |
| **Sanitization**| `sanitize_contact_sources` | Purges bookstore, catalog, and retailer false positives | DB Records |
| **Scheduling** | `run_scheduler_loop` | Runs scheduled recurring lead discovery tasks | Worker Process |
| **System** | `bootstrap_superadmin` | Seeds default admin, manager, and sales rep accounts | DB Records |
| **Exports** | `export_leads_csv` | Exports all pipeline leads to CSV | CSV File |
| **Exports** | `export_validated_author_leads`| Exports leads with verified author websites | CSV File |
| **Exports** | `export_contactable_leads_csv` | Exports leads having verified emails or phones | CSV File |
| **Exports** | `export_best_animation_leads` | Exports high-scoring hot leads with no public trailer | CSV File |

---

## 1. Data Ingestion & Seeding Commands

### `import_excel_leads`
Ingests Excel workbooks (`.xlsx`, `.xlsm`). Features automatic detection of shifted author/phone columns, publication date extraction, and lead deduplication against existing ASINs.

```powershell
python manage.py import_excel_leads <file_path> [--dry-run]
```
* **Arguments:**
  * `<file_path>` *(Required)*: Absolute or relative path to the `.xlsx` file.
  * `--dry-run` *(Optional)*: Previews changes and statistics without writing to the database.
* **Examples:**
  ```powershell
  python manage.py import_excel_leads "E:\yt-video\leads data.xlsx"
  python manage.py import_excel_leads "E:\yt-video\leads dev-ali.xlsx"
  ```

---

### `import_books_csv`
Imports raw CSV book catalogs and seeds them into the pipeline.

```powershell
python manage.py import_books_csv <csv_file> [--batch-size 100]
```
* **Arguments:**
  * `<csv_file>` *(Required)*: Path to CSV file containing `title` and `author`.
  * `--batch-size` *(Default: 100)*: Database insert batch size.

---

### `seed_demo`
Seeds the database with representative mock children's picture book records for testing and demonstration.

```powershell
python manage.py seed_demo
```

---

## 2. Lead Discovery & Research Commands

### `run_lead_research`
Executes an end-to-end research run for a specific search query.

```powershell
python manage.py run_lead_research --keyword <query> [options]
```
* **Options:**
  * `--keyword` *(Required)*: Search query (e.g. `"kids bedtime story picture book"`).
  * `--max-books` *(Default: `25`)*: Maximum books to discover.
  * `--provider` *(Default: `ddgs`)*: Search provider (`ddgs`, `tavily`, `brave`, `google_books`).
  * `--require-public-email`: Excludes leads that lack a public email.
  * `--no-video-search`: Skips YouTube and Vimeo trailer scanning.
  * `--no-ai`: Uses offline deterministic templates instead of Groq LLM.
* **Example:**
  ```powershell
  python manage.py run_lead_research --keyword "children picture book animal" --max-books 50 --provider ddgs
  ```

---

### `run_bulk_lead_research`
Loops through keyword suggestion groups until a target quota of qualified leads is reached.

```powershell
python manage.py run_bulk_lead_research --target-leads <count> [options]
```
* **Options:**
  * `--target-leads` *(Default: `700`)*: Stop threshold for qualified leads.
  * `--batch-size` *(Default: `25`)*: Books retrieved per keyword batch.
  * `--provider` *(Default: `tavily`)*: Search indexing provider.
  * `--output` *(Optional)*: File path to export compiled CSV.
* **Example:**
  ```powershell
  python manage.py run_bulk_lead_research --target-leads 100 --batch-size 25 --provider ddgs --output data/target_100_leads.csv
  ```

---

### `run_booklife_research`
Discovers independent authors through Publishers Weekly BookLife category listings.

```powershell
python manage.py run_booklife_research --category <slug> [options]
```
* **Options:**
  * `--category` *(Required)*: BookLife category slug (e.g. `fiction-romance`, `fiction-mystery`).
  * `--age-filter`: Age filter slug (e.g. `children-young-adult`).
  * `--max-books` *(Default: `25`)*: Max listings to index.

---

## 3. Web Scraping & Harvesting Commands

### `harvest_author_site_leads`
Performs deep crawling of known author website domains to extract emails, phones, and representation details.

```powershell
python manage.py harvest_author_site_leads [--limit 50] [--sleep 0.5]
```

---

### `pull_tavily_validated_leads`
Queries Tavily Search to identify official author websites and extracts contact coordinates.

```powershell
python manage.py pull_tavily_validated_leads --target-leads 200 --output data/tavily_leads.csv
```

---

### `scrape_author_visit_leads`
Targets school visit, author presentation, and speaking kit pages to harvest direct booking emails and phones.

```powershell
python manage.py scrape_author_visit_leads --target-leads 400 --output data/author_visit_leads.csv --sleep 0.2
```

---

### `scrape_scrapy_author_batches`
Runs high-throughput, asynchronous Scrapy crawlers across a targeted batch of author websites.

```powershell
python manage.py scrape_scrapy_author_batches --batch-size 50 --concurrency 8
```

---

## 4. Verification & Sanitization Commands

### `sanitize_contact_sources`
Scans all contact candidate records and removes catalog false positives (e.g. Open Library, Goodreads, university press bookstores).

```powershell
python manage.py sanitize_contact_sources
```

---

### `reverify_contacts`
Re-runs verification algorithms (syntax, domain alignment, and MX records) against existing contact candidates.

```powershell
python manage.py reverify_contacts [--all] [--limit 100]
```

---

### `enrich_existing_leads`
Repairs records with missing author names, scrapes Amazon ASIN profile data, and recalibrates scores.

```powershell
python manage.py enrich_existing_leads [--asin <asin>] [--dry-run] [--force]
```
* **Example:**
  ```powershell
  python manage.py enrich_existing_leads --asin B0OCTSHAR5 --force
  ```

---

## 5. Scheduler & Daemon Commands

### `run_scheduler_loop`
Executes recurring lead hunts configured via the web UI (`/scheduled-tasks/`).

```powershell
python manage.py run_scheduler_loop [--daemon] [--check-interval <seconds>]
```
* **Options:**
  * `--daemon`: Runs as a continuous background worker.
  * `--check-interval` *(Default: `60`)*: Seconds to sleep between checking for due tasks.
* **Example:**
  ```powershell
  python manage.py run_scheduler_loop --daemon --check-interval 60
  ```

---

## 6. Export Commands

### `export_leads_csv`
Dumps all active pipeline leads to CSV.

```powershell
python manage.py export_leads_csv [--output data/all_leads.csv]
```

---

### `export_best_animation_leads`
Filters and exports the highest-scoring leads (Score $\ge 75$, verified email, no existing trailer).

```powershell
python manage.py export_best_animation_leads [--output data/hot_animation_leads.csv]
```

---

### `export_contactable_leads_csv`
Exports all leads having at least one verified email or phone number.

```powershell
python manage.py export_contactable_leads_csv [--output data/contactable_leads.csv]
```
