<div align="center">
  <h1>🎬 Book Trailer Lead Finder</h1>
  <p><strong>Intelligent Lead Research & Discovery for Book Promos</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white" alt="Django" />
    <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/Bootstrap_5-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white" alt="Bootstrap" />
    <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
  </p>
</div>

Role-based access, private sales queues, daily assignment schedules, and security setup are documented in [Role access and lead assignment](docs/ROLE_ACCESS_AND_ASSIGNMENT.md).

---

## 📖 Overview

**Book Trailer Lead Finder** is a robust, evidence-first Django lead research system. It is designed to intelligently find, verify, and score children's book authors who may be the perfect fit for animated book trailers, promo videos, or short social ads.

Instead of guessing, the app provides hard evidence. Every contact signal is stored with its source URL and confidence score. When videos aren't found, we use safe language: *"No public video found in searched sources."*

---

## ✨ Features

### 🚀 Core Capabilities
* **Data Ingestion:** Import bulk book data via CSV effortlessly.
* **Smart Discovery:** Discovers Amazon book URLs from public search pages (without triggering Amazon anti-bot systems).
* **Deep Contact Mining:** Searches author websites, contact pages, publisher pages, and identity-matched public profiles. It makes one bounded, robots-aware pass through supported bio links such as Linktree, Carrd, and Substack.
* **Safe Extraction:** Extracts visible public emails, professional phone numbers, and common public email obfuscations (`[at]`, `(dot)`, URL-encoded `mailto:`, and Cloudflare email-protection markup) with a source URL for every candidate.
* **LLM Integration:** Uses Groq for structured data extraction and classification.
* **Export Ready:** Generates a sales-agent-ready brief and exports verified leads to CSV with source URLs and confidence metrics.
* **ISBN Intelligence:** Validates ISBN-10/13 checksums with three implementations, converts equivalent forms, reconciles exact Open Library and Google Books matches, and generates downloadable SVG barcodes.

### 🛡️ Advanced AI Verification & UX
* **Glassmorphic AI Reports:** Premium UI components featuring dynamic SVG progress rings mapping identity confidence scores.
* **Smart Rejection Filtering:** Rejects catalog/library/bookstore contacts (e.g., Open Library, Goodreads) while preserving valid literary agents (`representation_email`) and PR bookings (`publicist_email`).
* **Source-Audited Search:** Results are cached, DNS checks are remembered, and deep contact mining stops once trusted author-site evidence is secured.
* **Interactive Suggestions:** A modern keyword suggestion panel that features a smooth JavaScript typewriter animation.

---

## 🚫 What This Tool Does NOT Do

To maintain compliance and respect privacy, this system explicitly **does not**:
* Scrape Amazon product pages directly.
* Bypass CAPTCHAs, Cloudflare, or login walls.
* Use rotating proxies.
* Scrape private social media profiles (Facebook, Instagram, TikTok, etc.).
* Use leaked data, private enrichment tools, or people-search databases.
* Automatically send outreach emails.
* Make false claims (e.g., asserting an author definitely has no video).

---

## ⚙️ Quick Start

**Free-First Setup:** DDGS is the default no-key search provider. Groq, Tavily, Brave, and YouTube credentials are optional enhancements.

### 1. Installation
```powershell
# Navigate to the project directory
cd C:\Users\Ali.Raza\Desktop\lead-scraping\django\booktrailer_leads

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
copy .env.example .env
```

### 2. Database Setup & Run
```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Navigate to `http://127.0.0.1:8000/dashboard/` to view the app!

---

## 🔑 Environment Variables

Set these in your `.env` file (all are optional):
* `GROQ_API_KEY`: Improves book classification, contact extraction, and sales briefs.
* `TAVILY_API_KEY`: Paid search provider for higher volume.
* `BRAVE_API_KEY`: Paid search provider alternative.
* `YOUTUBE_API_KEY`: Enables official YouTube Data API video search.
* `APP_MAX_SOCIAL_CONTACT_PAGES`: Maximum supported bio-link pages to inspect per verified public profile (default: `5`, capped at `10`).
* `APP_SCHEDULED_TASK_LEASE_SECONDS`: How long a `running` scheduled task may remain unresponsive before the scheduler can safely recover it (default: `21600`, six hours).

### Free-first provider expectations

Open Library and the no-key Google Books endpoint improve coverage without a paid credential. They are public services, not unlimited infrastructure: fair-use limits, outages, incomplete records, and conflicting edition data remain possible. The app caches successful ISBN reconciliation for 24 hours, retains field-level source evidence, and sends conflicts to human review instead of claiming perfect accuracy.

---

## 🛠️ Usage Guides

### 📥 Import CSV
Import existing leads from CSV, XLSX, or XLSM files. The upload page accepts standard columns such as `title`/`book_title` and `author`/`author_name`, detects client headers such as `Book / Project` and `Author / Owner`, and can re-import the app's own XLSX export.

Manual imports create book, author, lead, contact, and source-evidence records immediately. Video checks, email/phone verification, and AI sales briefs are optional and off by default, so supplied data is never replaced by an automatic research run.
```powershell
python manage.py import_books_csv data\demo_books.csv
```
*UI Route:* `/import-csv/`

### 🔍 Run Keyword Research
Discover new books matching specific keywords. The queries search public results for Amazon URLs safely.
```powershell
python manage.py run_lead_research --keyword "children picture book" --max-books 25 --provider ddgs
```

---

## 📈 Lead Scoring & Verification

Scores are deterministic out of **100**:
* **Book Fit:** Checks for children's/picture-book signals, Amazon URL, ASIN, and recent publication metadata.
* **Contactability:** Evaluates public emails, contact pages, websites, social profiles, and publisher contacts.
* **Video Opportunity:** Positive score for `no_public_video_found`; penalties if existing trailers are found.
* **Data Quality:** Boosts for high confidence; penalties for unclear identities or mismatch risks.

*A lead is considered "Hot" if the score is >= 75, has a public email, Amazon URL, and no clear video found.*

Contact verification uses independently recorded checks: syntax, source trust, author identity alignment, contact role, optional DNS/SMTP delivery evidence, and corroboration. A lead is classified as **Verified**, **Not verified**, or **Other**; the score shows the strength of the available evidence.

No public-data workflow can prove a person owns a mailbox or guarantee “10/10 accuracy.” DNS and SMTP results can also be blocked, catch-all, or transient. Review the recorded evidence and respect `do_not_contact` before any outreach.

## Scheduled Lead Hunts

Create a recurring hunt at `/scheduled-tasks/` to run the same evidence-first pipeline daily, at an hourly interval, weekly, or on selected weekdays. Each task has a verified-lead target, new-book deduplication, a contact requirement, and optional network email checks.

Run currently due tasks once:

```powershell
python manage.py run_scheduler_loop
```

Or run it as a long-lived worker:

```powershell
python manage.py run_scheduler_loop --daemon --check-interval=60
```

Only run one scheduler service in production. Task claims prevent duplicate work, while the lease setting lets a later scheduler tick recover a task abandoned by a crashed process. See [walkthrough.md](walkthrough.md) for operating details and verification commands.

---

## 📝 Sales Agent Briefs

Each verified lead generates an AI-assisted sales brief. This brief avoids aggressive claims, fake urgency, or mentioning data access. It provides:
* Summary & Book Data
* Why the lead matters
* Contact path & confidence
* Recommended pitch angle & suggested first line
* Source links for every data point

---

## 🚀 Deployment Notes

* Keep `DEBUG=False` in production.
* Set a strong `SECRET_KEY`.
* Enforce HTTPS.
* Use **PostgreSQL** in production instead of SQLite.
* Run `run_scheduler_loop --daemon` through a process manager that restarts it after host or process failure.
* Move large research batches to a supervised job queue before scaling beyond one worker.

---

<div align="center">
  <p>Built for evidence-based research and high-quality outreach.</p>
</div>
