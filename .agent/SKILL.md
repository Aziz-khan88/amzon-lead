# 🛠️ Programmatic Skills Catalog (SKILL.md)

*Note: This file mirrors [SKILLS.md](SKILLS.md) to support agent frameworks that expect singular `SKILL.md`.*

Please refer to the comprehensive [**SKILLS.md**](SKILLS.md) for full parameters, CLI syntax, agent role mappings, and input/output contracts across all 22 management commands and programmatic services.

### Quick Reference Matrix

| Skill Name | Command | Primary Purpose |
| :--- | :--- | :--- |
| **Excel Ingestion** | `python manage.py import_excel_leads` | Ingests production Excel files with column-shift protection |
| **CSV Seeding** | `python manage.py import_books_csv` | Ingests raw CSV book seed lists |
| **Demo Seeder** | `python manage.py seed_demo` | Generates realistic mock picture book leads |
| **Keyword Discovery** | `python manage.py run_lead_research` | Single-batch keyword research pipeline |
| **Bulk Discovery** | `python manage.py run_bulk_lead_research` | Multi-batch looping research to reach quota |
| **BookLife Scraper**| `python manage.py run_booklife_research` | Category scraping from PW BookLife index |
| **Site Harvester** | `python manage.py harvest_author_site_leads`| Direct author website contact crawler |
| **Tavily Lookup** | `python manage.py pull_tavily_validated_leads` | Search author pages via Tavily API |
| **School Kit Scraper**| `python manage.py scrape_author_visit_leads` | Mines school visit and speaker kit pages |
| **School Batch Runner**| `python manage.py scrape_author_visit_batches`| Runs author visit crawler across multiple queries|
| **Blog Harvester** | `python manage.py scrape_blog_book_leads` | Crawls children's book blogs & awards |
| **Scrapy Spiders** | `python manage.py scrape_scrapy_author_batches`| High-throughput concurrent Scrapy crawler |
| **ASIN Repair** | `python manage.py enrich_existing_leads` | Backfills missing metadata & repairs names |
| **Catalog Sanitize**| `python manage.py sanitize_contact_sources` | Purges bookstore/catalog false positives |
| **Reverify Contacts**| `python manage.py reverify_contacts` | Re-runs verification on candidate contacts |
| **Stale Reverify** | `python manage.py reverify_stale_contacts` | Re-audits contacts older than $N$ days |
| **Scheduler Daemon**| `python manage.py run_scheduler_loop` | Executes recurring research hunts |
| **Superadmin Setup**| `python manage.py bootstrap_superadmin` | Bootstraps default admin/manager/sales accounts|
| **Export All CSV** | `python manage.py export_leads_csv` | Exports all pipeline leads to CSV |
| **Export Validated**| `python manage.py export_validated_author_leads`| Exports leads with verified author websites |
| **Export Contactable**| `python manage.py export_contactable_leads_csv`| Exports leads with verified email or phone |
| **Export Best Hot** | `python manage.py export_best_animation_leads` | Exports hot leads with no existing trailer |
