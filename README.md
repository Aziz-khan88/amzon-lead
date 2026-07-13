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

---

## 📖 Overview

**Book Trailer Lead Finder** is a robust, evidence-first Django lead research system. It is designed to intelligently find, verify, and score children's book authors who may be the perfect fit for animated book trailers, promo videos, or short social ads.

Instead of guessing, the app provides hard evidence. Every contact signal is stored with its source URL and confidence score. When videos aren't found, we use safe language: *"No public video found in searched sources."*

---

## ✨ Features

### 🚀 Core Capabilities
* **Data Ingestion:** Import bulk book data via CSV effortlessly.
* **Smart Discovery:** Discovers Amazon book URLs from public search pages (without triggering Amazon anti-bot systems).
* **Deep Contact Mining:** Searches for author websites, contact pages, publisher pages, and public social links (YouTube, Vimeo, etc.).
* **Safe Extraction:** Intelligently extracts public emails, professional phone numbers, social URLs, and location signals.
* **LLM Integration:** Uses Groq for structured data extraction and classification.
* **Export Ready:** Generates a sales-agent-ready brief and exports verified leads to CSV with source URLs and confidence metrics.

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

---

## 🛠️ Usage Guides

### 📥 Import CSV
Import existing leads from a CSV file containing columns like `title`, `author`, `amazon_url`, `asin`, etc.
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
* Implement background job queues (like Celery) before running large research batches.

---

<div align="center">
  <p>Built for evidence-based research and high-quality outreach.</p>
</div>