# Dependency Review

This app should optimize for evidence quality, compliance, and maintainability rather than installing every scraping or AI package available.

## Keep

- `Django`, `djangorestframework`, `python-dotenv`: current app/runtime configuration.
- `requests`, `httpx`: synchronous crawling plus search API clients.
- `beautifulsoup4`, `lxml`, `tldextract`: public page parsing, link extraction, and domain checks.
- `ddgs`, `tavily-python`, `google-api-python-client`: configured search and YouTube providers.
- `scrapy`: used by the batch author-site scraping command.
- `email-validator`, `dnspython`, `phonenumbers`: contact syntax, DNS, and phone validation.
- `openpyxl`: Excel workbook export.
- `groq`: optional structured AI extraction/classification with deterministic fallback.
- `psycopg[binary]`: PostgreSQL support for production `DATABASE_URL`.

## Do Not Add Until Code Needs Them

- Duplicate config libraries: `django-environ`, `python-decouple`, `dj-database-url`.
- Unused async stacks: `aiohttp`, `aiodns`, `brotli`.
- Unused parsers: `html5lib`, `parsel`, `selectolax`, `trafilatura`, `readability-lxml`.
- Heavy local AI/vector packages: `openai`, `litellm`, `instructor`, `tiktoken`, `sentence-transformers`, `faiss-cpu`.
- Data science packages: `pandas`, `numpy`, `xlsxwriter`.
- Background workers: `celery`, `redis`, `django-redis`, `flower`.
- File/PDF exporters: `python-docx`, `reportlab`.
- Misc helpers: `PyJWT`, `cryptography`, `python-slugify`, `nameparser`, `pycountry`, `tqdm`, `orjson`, `rich`, `schedule`.
- Lead/private APIs: `linkedin-api`, `pyhunter`.

## Avoid

- Direct use of `cloudscraper`, `fake-useragent`, `scrapy-rotating-proxies`, `scrapy-user-agents`, `playwright`, and `selenium` should not be part of this product unless there is a separate legal/compliance review and a clear permitted use case. The README policy says the app does not bypass CAPTCHA, Cloudflare, login walls, rate limits, or private pages.

## Data Quality Rule

No package can make lead data 100% correct. The professional target is source-backed data with confidence scores, source URLs, deterministic validation, clear warnings, and manual review before outreach.
