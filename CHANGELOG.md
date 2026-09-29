# 📜 Changelog

All notable changes to the **Book Trailer Lead Finder** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.0.0] - 2026-09-25

### 🚀 Major Highlights
* **Full Production Excel Ingestion:** Loaded, deduplicated, and enriched **1,843 Books** and **1,841 Leads** from `leads data.xlsx` and `leads dev-ali.xlsx`.
* **Bulletproof 7-Column Responsive Layout:** Engineered exact column width allocations (`38px`, `32%`, `27%`, `11%`, `10%`, `11%`, `9%`) tailored for 1440×900 desktop and laptop screens with zero horizontal scroll.

### 🐛 Fixed & Polished
* **Table Row Dropdown Z-Index Stacking Bug:**
  * Fixed bug where subsequent table row elements (`UNASSIGNED` task badges and `...` buttons) painted over open dropdown menus.
  * Removed `transform: translateY(0)` from `@keyframes ux-row-in`, eliminating rogue Stacking Contexts across all table rows.
  * Updated `@keyframes dropdownFadeIn` to animate only `opacity` instead of overriding Bootstrap Popper's inline translation coordinates.
  * Added Section 25 in `ux-polish.css` and `setupDropdownElevation()` in `ux-polish.js` to dynamically elevate active dropdown rows and cells to `z-index: 1050 !important;`.
* **Shifted Column Data Recovery:**
  * Recovered 20 shifted email addresses from `dev-ali.xlsx` where emails were stored under proof URLs.
  * Cleaned 112 raw narrative publication date entries into standardized `YYYY-MM-DD` formats.
  * Added automated shift safeguards in `import_excel_leads` to detect author names misplaced in the Phone column.
* **Browser Cache Invalidation:**
  * Bumped `app.css`, `ux-polish.css`, `app.js`, and `ux-polish.js` cache-busting strings to `?v=3.0` in `base.html`.

---

## [2.9.0] - 2026-09-16

### ✨ Added
* **ISBN & ASIN Intelligence Suite:**
  * Added checksum validation for ISBN-10, ISBN-13, and ASIN.
  * Integrated multi-provider reconciliation via Open Library and Google Books API.
  * Added dynamic downloadable SVG EAN-13 barcode generation endpoint (`/isbn-search/barcode/<identifier>.svg`).
* **Role-Based Access Control (RBAC):**
  * Added `UserProfile` tiers: `superadmin`, `manager`, and `sales`.
  * Implemented private sales rep lead queues (`/leads/?assigned_to=me`) and assignment distribution engine.

### 🎨 UI/UX Improvements
* **Glassmorphic Lead Detail Page:** Implemented dynamic SVG progress rings mapping confidence scores.
* **Interactive Suggestions:** Added typewriter animation to keyword suggester panel.
* **Animated Counter Widgets:** Real-time numerical roll-up animations for dashboard KPI metric cards.

---

## [2.5.0] - 2026-08-07

### ✨ Added
* **Recurring Scheduled Lead Hunts:**
  * Added `ScheduledLeadTask` model and web UI (`/scheduled-tasks/`).
  * Created `run_scheduler_loop` management command with `--daemon` worker mode.
  * Added automated crash recovery using lease timeouts (`APP_SCHEDULED_TASK_LEASE_SECONDS`).
* **Bounded Bio-Link Crawler:**
  * Added single-pass crawling for verified social profiles pointing to Linktree, Carrd, and Substack.
  * Integrated rate-limiting and polite crawling delays (`--sleep`).

### 🛡️ Security & Compliance
* Added `DoNotContact` global suppression list model and enforcement hooks.
* Added catalog rejection filters discarding bookstore/library emails (Open Library, Goodreads, MIT Press).

---

## [2.0.0] - 2026-07-02

### 🚀 Initial Platform Release
* **Multi-Agent Pipeline:** Built 5 specialized agents (Scout, Harvester, Auditor, Copywriter, Coordinator).
* **Deterministic Lead Scoring:** 0–100 point formula evaluating Book Fit, Contactability, Video Opportunity, and Data Quality.
* **Anti-Hallucination Video Classification:** Transparent detection of YouTube/Vimeo trailers with fallback to *"No public video found in searched sources"*.
* **Groq LLM Integration:** Automated sales brief and custom first-line pitch hook generation with deterministic offline fallback.
* **Exporting:** Direct streaming of CSV and XLSX exports.
