# 📖 User & Sales Team Guide

Welcome to the **Book Trailer Lead Finder** user manual. This guide is tailored for sales representatives, outreach specialists, lead researchers, and marketing agency managers seeking high-conversion opportunities for children's book trailers.

---

## 1. Role Profiles & Navigation

The platform provides a tailored experience depending on your assigned role:

| Role | Primary Daily Views | Key Responsibilities |
| :--- | :--- | :--- |
| **Sales Rep** | `/leads/?assigned_to=me` | Review assigned leads, copy verified contacts, read AI sales briefs, update outreach stages. |
| **Manager** | `/dashboard/`, `/runs/`, `/assignment-schedules/` | Monitor crawler velocity, launch research hunts, distribute leads to reps, review conversion metrics. |
| **Superadmin** | Full Access & `/team/` | Manage API tokens, configure team accounts, customize scoring thresholds, purge suppressed leads. |

---

## 2. Navigating the Dashboard (`/dashboard/`)

The Dashboard provides high-level health and volume metrics:

```text
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  TOTAL CRAWLED  │ │ VERIFIED READY  │ │  NEEDS REVIEW   │ │   CONTACTABLE   │
│      1,841      │ │      1,042      │ │       799       │ │      1,479      │
│  ↗ 12% vs last  │ │  ✓ Deliverable  │ │  ⚠ Human Audit  │ │  ↗ 15% vs last  │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

* **Total Crawled:** Total books identified in database.
* **Verified Ready:** Leads passing all syntax, domain-alignment, and deliverability checks (Scores $\ge 75$).
* **Needs Review:** Leads with single-source signals, missing ASINs, or unresolved author name ambiguities.
* **Contactable:** Leads possessing at least one confirmed email or phone number.

---

## 3. Working with the Leads Directory (`/leads/`)

The Leads Directory is the central command center for researching and qualifying prospects.

### 3.1 Instant Search & Sorting
* **Search Bar:** Type any part of a book title, author name, ASIN, or email address. Press `Ctrl + K` or `Enter` to filter instantly.
* **Sort Dropdown:**
  * `Newest First` (Default): Recent additions at the top.
  * `Highest Score`: Top-ranked leads with highest evidence confidence.
  * `Publication Date`: New book releases ready for promo campaigns.

### 3.2 Quick Filter Pills
Single-click pills allow you to filter the 1,841-lead database in milliseconds:
* `All Leads (1841)`: Full catalog.
* `Verified Ready (1042)`: High-scoring, contactable leads.
* `Verified Email (1479)`: Leads with a deliverable email address.
* `Verified Phone (456)`: Leads with a validated direct phone number.
* `No Video`: Authors with no existing public book trailers detected.
* `Needs Review (799)`: Leads requiring manual review before outreach.

---

## 4. Understanding Table Columns (7-Column Layout)

The table is designed for maximum clarity on laptop and desktop displays (1440×900):

| Column | Proportion | What It Shows & How to Use It |
| :--- | :---: | :--- |
| **1. Select** | `38px` | Checkbox for bulk actions (Assign Rep, Mark Contacted, Delete). |
| **2. Book Details** | `32%` | Cover thumbnail, full title with 2-line clamp, ASIN tag, and Video Status badge (`No video`, `Trailer`, `Read aloud`, `Not checked`). |
| **3. Author & Contact** | `27%` | Author name link to Amazon/website, verified email address, **One-Click "Copy" button**, and verification pill (`Verified` or `Check`). |
| **4. Channels** | `11%` | Badges for discovered presence: Amazon store, canonical website, email, and social networks. |
| **5. Published** | `10%` | Official release date (`YYYY-MM-DD`). |
| **6. Task** | `11%` | Workflow assignment pill (`UNASSIGNED` or sales rep name). |
| **7. Actions** | `9%` | **3-Dots Menu (`...`)**: View Details, Generate AI Pitch, Open Amazon Book, Do Not Contact, Delete Lead. |

> [!TIP]
> Click the **Copy** button next to any email address to immediately copy it to your clipboard without opening the detail view!

---

## 5. Lead Detail & AI Sales Brief (`/leads/<id>/`)

Clicking any row opens the full Lead Profile:

### 5.1 Evidence Audit Trail
* **Source URLs:** Direct links to author websites, publisher pages, and interviews where contact coordinates were observed.
* **Confidence Rating:** Explicit percentage showing identity certainty.
* **Anti-Hallucination Video Audit:** Explicit listing of searched YouTube and Vimeo queries that confirmed no existing trailer.

### 5.2 AI Sales Pitch Generator
Powered by Groq LLM (with deterministic local fallback):
* **Hook Angle:** Why this book is ideal for an animated promo (e.g. bedtime themes, animal characters, bright illustrations).
* **Suggested First Line:** A personalized opener referencing the author's specific work.
* **Compliance Rules:** Clear reminders for sales reps:
  * ❌ *Never tell an author their book is performing poorly.*
  * ❌ *Never claim you have "exclusive data."*
  * ✅ *Compliment the visual art style and propose a 30-second social media animation teaser.*

---

## 6. Managing the Sales Outreach Pipeline

Track every lead's progress through the sales cycle:

1. **Pending:** Lead is assigned to you but not yet contacted.
2. **In Progress:** Researching author background or drafting custom pitch.
3. **Contacted:** Initial email or pitch message sent.
4. **Meeting Booked:** Author responded and scheduled a trailer consultation call.
5. **Closed Won:** Contract signed for animated trailer production!
6. **Lost / Passed:** Author declined or timing wasn't right.

---

## 7. Exporting Lead Data

Export filtered datasets at any time using the header buttons:
* **Export CSV:** Raw data export for CRM ingestion (HubSpot, Salesforce, Lemlist).
* **Export Excel:** Formatted `.xlsx` spreadsheet with styled headers, auto-fit columns, and clickable evidence URLs.

---

## 8. Launching New Research Runs

To discover fresh leads:
1. Navigate to **New Research** (`/runs/new/`).
2. Enter a focused keyword (e.g., `"kids picture book bedtime"` or `"children books animal adventures"`).
3. Select your provider (`ddgs` for free search, `tavily` for high-volume paid search).
4. Set max books (e.g. `25` or `50`).
5. Click **Start Research Run**. Monitor live progress in the real-time agent console.

---

## 9. Suppression & "Do Not Contact" Management

If an author requests opt-out:
1. Click the **3-Dots (`...`)** button on the lead row.
2. Select **Do Not Contact**.
3. Confirm the modal prompt.
*Result:* The author name, email, and domain are permanently suppressed across all current and future crawler runs.
