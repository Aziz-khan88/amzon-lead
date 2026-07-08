# Book Trailer Lead Finder

Book Trailer Lead Finder is a Django lead research system for finding children's book authors who may be a fit for animated book trailers, animated promo videos, or short social ads.

The app is evidence-first rather than guess-first. Important fields are stored with source URLs and confidence where available. Missing data is represented as missing. Unclear author identity stays unclear. When video searches do not find a trailer, the app uses the safe wording: **"No public video found in searched sources."**

## What This Tool Does

- Imports known book data from CSV.
- Discovers Amazon book URLs from public search result pages without fetching Amazon product pages.
- Adds a BookLife category runner that can seed projects into the same author enrichment pipeline.
- Parses ASINs from Amazon URLs.
- Searches for author websites, contact pages, publisher pages, public social links, and public YouTube/Vimeo evidence.
- Rejects catalog/library/bookstore contacts such as Open Library, Archive.org, Goodreads, WorldCat, LibraryThing, MIT Press Bookstore, AbeBooks, and retailer support pages as author contact data.
- Safely fetches public author/publisher pages with SSRF protections, timeouts, robots checks, and polite delay.
- Extracts visible public emails, professional phone numbers, social URLs, and location signals.
- Uses Groq for structured extraction/classification when configured.
- Runs deterministic fallbacks when API keys are missing.
- Scores leads and generates a sales-agent-ready brief.
- Exports leads to CSV with source URLs, confidence, warnings, and missing data.

## Advanced AI Verification & UX Features

- **Multi-Layered AI Verification Auditing:** Includes a premium, glassmorphic **AI Verification Report** card in the lead detail view. It renders a dynamic SVG progress ring mapping the identity confidence score and logs step-by-step audit reasoning and verification sources.
- **Support for Booking / Agency Channels:** Safely accepts literary agent (`representation_email`) and PR booking (`publicist_email`) channels as verified contact paths, preventing false programmatic rejections.
- **Fast Source-Audited Search:** Search results are cached for a short TTL, repeated DNS checks are cached, and deep contact search stops once trusted author-site evidence is found.
- **Interactive Auto-Typing Badges:** A modern keyword suggestion badge panel on the "New Run" page with a smooth JavaScript typewriter animation that types selections out character-by-character into the search query box!

## What This Tool Does Not Do

- It does not scrape Amazon product pages.
- It does not bypass CAPTCHA, Cloudflare, login walls, or rate limits.
- It does not use rotating proxies.
- It does not scrape private Facebook, Instagram, TikTok, or other logged-in pages.
- It does not use people-search databases, leaked data, private enrichment tools, or hidden personal data.
- It does not auto-send outreach emails.
- It does not claim an author has no video.

## Compliance Policy

Use only public professional/contact signals. Every contact detail should have a source URL and confidence. Leads default to `needs_review`. Sales agents must manually verify the evidence before outreach. Leads can be marked `do_not_contact`, and that clamps scoring to rejected.

## Why Amazon Pages Are Not Scraped

Amazon pages can have terms, bot controls, dynamic rendering, and anti-abuse systems. This MVP only uses public search-result metadata and user-supplied CSV data. Amazon URLs are normalized from result URLs or CSV values, and ASIN parsing is deterministic.

## Free-First Setup

DDGS is the default no-key search provider. Groq, Tavily, Brave, YouTube, and Amazon Creators credentials are optional enhancements.

```powershell
cd C:\Users\Ali.Raza\Desktop\lead-scraping\django\booktrailer_leads
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## API Keys

Set these in `.env` when available:

- `GROQ_API_KEY`: improves book classification, contact extraction, video classification, and sales briefs.
- `TAVILY_API_KEY`: optional paid search provider.
- `BRAVE_API_KEY`: optional paid search provider.
- `YOUTUBE_API_KEY`: enables YouTube Data API video search; the MVP uses web search fallback when missing.
- `AMAZON_CREATORS_CLIENT_ID` / `AMAZON_CREATORS_CLIENT_SECRET`: placeholder only until official endpoint details are available.

Keys are never displayed in full in the UI.

## Run Locally

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/dashboard/`.

## Import CSV

CSV accepts:

- `title` or `book_title`
- `author` or `author_name`
- `illustrator` or `illustrator_name`
- `amazon_url` or `amazon_book_url`
- `asin`
- `category`
- `review_count`
- `rating`
- `publisher`
- `publication_date`
- `cover_image_url`

Command:

```powershell
python manage.py import_books_csv data\demo_books.csv
```

UI:

```text
/import-csv/
```

## Run Keyword Research

```powershell
python manage.py run_lead_research --keyword "children picture book" --max-books 25 --provider ddgs
```

The discovery queries search public search results for Amazon URLs. The app does not fetch Amazon pages.

## Run BookLife Research

Use the `BookLife Run` nav tab or run:

```powershell
python manage.py run_booklife_research --category fiction-romance --age-filter children-young-adult --max-books 25
```

BookLife categories currently available in the UI:

- Fiction: Mystery/Thriller, Sci-Fi/Fantasy/Horror, Romance, General Fiction.
- Nonfiction: True Crime, History & Military, Memoir, Food & Cooking, Health/Diet/Parenting/Home/Crafts/Gardening, Self-Help/Relationships/Psychology/Philosophy/Fashion, Business & Personal Finance, Pop Culture & Sports, Music/Performing Arts/Travel, Political & Social Sciences, Art & Photography, Science/Nature/Technology, Lit Crit/Lit Bio/Essay/Film, Other Nonfiction.
- Other: Poetry, Comics/Graphic Novels, Spirituality/Inspirational.

The BookLife runner is built around the current Browse page structure: category pages at `/project-browse/...` expose book rows with title, author, cover, category, and summary. The runner respects `robots.txt` by default. As of the latest implementation check, BookLife disallows generic automated fetching, so the runner uses search-index snippets as a fallback unless you have permission and set `BOOKLIFE_DIRECT_FETCH_ALLOWED=1`. Project detail pages are optional because some return automated-request challenges; enable them with `BOOKLIFE_FETCH_PROJECT_DETAILS=1` only when needed. After project discovery, enrichment uses the configured search provider to find official author sites, public social profiles, contact pages, and video evidence.

## Lead Scoring

Scores are deterministic out of 100:

- Book fit: children's/picture-book signals, Amazon URL, ASIN, recent publication, review metadata.
- Contactability: public email, contact page, website, social profile, location, publisher contact.
- Video opportunity: positive score for `no_public_video_found` after completed search; penalties for found trailers/animated videos.
- Data quality: boosts for high identity/contact confidence; penalties for unclear identity, low extraction confidence, mismatch risk, non-children books, and do-not-contact.

Hot leads require score >= 75, public email, Amazon URL, and video status of `no_public_video_found` or `unclear`.

## Video Status

The app uses safe labels:

- `found_animated_video`
- `found_trailer`
- `found_read_aloud_only`
- `unclear`
- `no_public_video_found`
- `not_checked`

The phrase "No public video found in searched sources" means only that the configured sources did not reveal a public video.

## Sales Agent Brief

Each lead gets a brief with summary, book data, why the lead matters, video opportunity, contact path, confidence, recommended pitch angle, suggested first line, what to say, what not to say, and source links.

The brief avoids claims such as "you have no video," "your marketing is poor," fake urgency, fake partnerships, and any suggestion of private data access.

## Evidence and Source URLs

Evidence rows store:

- field name
- field value
- source URL
- source title/snippet
- confidence
- evidence type

The lead detail page shows the evidence timeline so a sales agent can trace where each important data point came from.

## Export CSV

```text
/export/leads.csv
```

The export includes the requested sales-agent columns, including contact source URLs, video evidence URLs, missing data, warnings, and all source URLs.

## Troubleshooting

- Missing search API keys do not crash the app; it falls back to DDGS.
- Missing Groq key does not stop runs; deterministic low-confidence fallbacks are used.
- External sites may block crawling or disallow robots access; those pages are skipped.
- If a run returns few books, try a narrower keyword or import a CSV seed list.
- If `ddgs` behavior changes, use Tavily or Brave for more stable search results.

## SQLite to PostgreSQL

Set `DATABASE_URL`:

```env
DATABASE_URL="postgresql://user:password@localhost:5432/booktrailer_leads"
```

Install a PostgreSQL driver if your environment does not already include one, then run:

```powershell
python manage.py migrate
```

## Deployment Notes

- Keep `DEBUG=False`.
- Set a strong `SECRET_KEY`.
- Use HTTPS.
- Use PostgreSQL for production.
- Add background jobs before running large research batches.
- Keep request limits, crawl depth, and polite delays conservative.
- Do not add automated outreach without a separate compliance review.

## Amazon Creators TODO

`AmazonCreatorsProvider` is intentionally a placeholder. It should only be implemented after official endpoint documentation and credentials are available. The MVP remains fully usable via CSV and search-result discovery.

## Tests

```powershell
pytest
```

The test suite covers Amazon URL parsing, dedupe, scoring, contact regex, video classification, and quality gate approval rules.
#   a m z o n - l e a d  
 