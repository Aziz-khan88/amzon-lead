# 🔄 Multi-Agent Orchestration Workflows (WORKFLOWS.md)

This document details the standard operating procedures (SOP), sequence diagrams, and lifecycle state machines governing autonomous agent workflows within the **Book Trailer Lead Finder** application.

---

## 📑 Core Workflows Overview

```mermaid
graph TD
    WF1["1. End-to-End Keyword Discovery & Research"]
    WF2["2. Excel Ingestion & Shift Recovery"]
    WF3["3. Bounded Bio-Link Crawling (Linktree / Carrd)"]
    WF4["4. ISBN Reconciliation & Barcode Generation"]
    WF5["5. Background Scheduler Daemon & Lease Recovery"]
    WF6["6. Sales Pipeline & Daily Quota Distribution"]
```

---

## 1. End-to-End Keyword Discovery & Assembly Workflow

This workflow represents the standard automated research pipeline executed when an operator or scheduler enters a search query.

```mermaid
sequenceDiagram
    autonumber
    actor User as Operator / Scheduler
    participant Scout as 1. Scout Agent
    participant Harvester as 2. Harvester Agent
    participant Auditor as 3. Auditor Agent
    participant Copywriter as 4. Copywriter Agent
    participant DB as Django ORM / Database

    User->>Scout: Execute research query (e.g. "kids picture book bedtime")
    Scout->>Scout: Query public search index (DDGS / Tavily)
    Scout->>Scout: Extract Amazon URLs, Book Titles, Authors & ASINs
    Scout->>DB: Create ResearchRun and Book records
    Scout->>Harvester: Pass Book candidates for enrichment
    
    Harvester->>Harvester: Search for author website and contact pages
    Harvester->>Harvester: Check YouTube / Vimeo APIs for existing trailers
    Harvester->>Harvester: Inspect public bio-links (Linktree, Carrd)
    Harvester-->>Auditor: Contact candidates, domain data, and video evidence
    
    Auditor->>Auditor: Gate 1: Obfuscation de-cloaking (decode [at], mailto:)
    Auditor->>Auditor: Gate 2: Catalog rejection filter (drop OpenLibrary, Goodreads)
    Auditor->>Auditor: Gate 3: Author identity alignment (domain vs author name)
    Auditor->>Auditor: Gate 4: Optional DNS MX check
    Auditor->>Auditor: Compute deterministic 0-100 score
    Auditor->>DB: Save Lead, ContactCandidates, and Evidence records
    
    Auditor->>Copywriter: Pass qualified leads
    Copywriter->>Copywriter: Query Groq LLM (or deterministic fallback)
    Copywriter->>DB: Save SalesAgentBrief (sales hook & custom first line)
    Copywriter-->>User: Complete verified leads visible in UI
```

---

## 2. Excel Dataset Ingestion & Shift Recovery Workflow

Ingests external client spreadsheets (`leads data.xlsx`, `leads dev-ali.xlsx`) with automated data cleaning and anomaly correction.

```mermaid
flowchart TD
    A[Start: python manage.py import_excel_leads] --> B[Load Workbook via openpyxl]
    B --> C[Normalize Headers: Book Name, Author, Phone, Email]
    C --> D{Author Column Shifted?}
    D -- "Yes (author in Phone column)" --> E[Swap Author and Phone, Delete Bogus Contact]
    D -- "No" --> F[Keep Author Name]
    E --> G{Email Column Empty?}
    F --> G
    G -- "Yes & Email in Proof URL" --> H[Extract Email from Proof URL]
    G -- "No" --> I[Keep Email]
    H --> J[Parse & Clean Publication Date]
    I --> J
    J --> K[Regex Extract YYYY-MM-DD from Narrative Text]
    K --> L{ASIN Exists in DB?}
    L -- "Yes" --> M[Enrich Existing Book & Lead Record]
    L -- "No" --> N[Insert New Book, AuthorProfile & Lead]
    M --> O[Attach ContactCandidate & Evidence Records]
    N --> O
    O --> P[Create ResearchRun Record & Commit Transaction]
```

### Anomaly Recovery Rules:
1. **Author Misplacement Rule:** If `Author / Owner Name` contains descriptive keywords (e.g. `"children"`, `"page"`, `"verified"`) and `Phone` contains text without digits, swap `author_name = raw_phone` and discard `phone`.
2. **Shifted Email Rule:** If `Email` is empty and `Email Proof URL` contains an `@` symbol without `http`, assign `email = email_proof_url`.
3. **Date Regularization Rule:** Apply regex pattern `r'\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b'` to extract standard dates from long review paragraphs.

---

## 3. Bounded Bio-Link Crawling Workflow

Targets secondary link hubs to discover author contact coordinates safely.

```mermaid
sequenceDiagram
    autonumber
    participant Harvester as Harvester Agent
    participant Target as Bio-Link Page (Linktree / Carrd / Substack)
    participant Engine as Verification Engine
    participant DB as Database

    Harvester->>Harvester: Detect social link matching supported domain
    Harvester->>Target: Check robots.txt and request page headers
    Target-->>Harvester: HTTP 200 OK (Content-Type: text/html)
    Harvester->>Harvester: Parse links, visible emails, and social handles
    Harvester->>Harvester: Cap crawl to max 5 outbound pages
    Harvester->>Engine: Pass raw contact strings and source URL
    Engine->>Engine: Decode Cloudflare cfemail and HTML entities
    Engine->>DB: Save ContactCandidate with channel="email" and source_url
```

---

## 4. ISBN Reconciliation & Barcode Generation Workflow

Validates international standard book numbers and compiles multi-catalog metadata.

```mermaid
flowchart TD
    A[Identifier Input: ISBN-10 / ISBN-13 / ASIN] --> B[Triple-Checksum Algorithm Check]
    B --> C{Checksum Valid?}
    C -- "No" --> D[Return Error: Invalid Checksum]
    C -- "Yes" --> E[Bidirectional Conversion: Compute ISBN-10 and ISBN-13]
    E --> F[Generate Dynamic Vector EAN-13 SVG Barcode]
    E --> G[Concurrent API Lookup: Open Library + Google Books]
    G --> H[Reconcile Title, Author, Publisher, Page Count]
    H --> I{Match Found?}
    I -- "Yes" --> J[Present Verified Book Profile in UI]
    I -- "No" --> K[Fallback to Public Search Discovery]
    J --> L[Optional: Convert to Outreach Lead]
```

---

## 5. Background Scheduler Daemon & Lease Recovery Workflow

Executes recurring lead research tasks without supervisor intervention.

```mermaid
stateDiagram-v2
    [*] --> Idle: Worker Start
    Idle --> CheckingDue: Check every 60s
    CheckingDue --> ReclaimingStale: Look for running tasks older than 6 hours
    ReclaimingStale --> ClaimingTask: Acquire atomic row lock (select_for_update)
    ClaimingTask --> ExecutingRun: Status set to "running", lease timestamp updated
    ExecutingRun --> CheckingTarget: Evaluate target lead quota
    CheckingTarget --> ExecutingRun: Target not met
    CheckingTarget --> CompletingRun: Target met or candidates exhausted
    CompletingRun --> SchedulingNext: Calculate next_run_at in local TIME_ZONE
    SchedulingNext --> Idle: Return to sleep
```

---

## 6. Sales Pipeline & Daily Quota Distribution Workflow

Automates daily lead delivery to sales reps while preserving history and suppression rules.

```mermaid
sequenceDiagram
    autonumber
    actor Mgr as Sales Manager
    participant Sched as Daily Assignment Schedule
    participant DB as Lead Repository
    actor Rep as Sales Representative

    Mgr->>Sched: Create schedule (50 leads/day, Mon-Fri, Min Score 75, Rep: sales_1)
    Sched->>Sched: Trigger execution at configured time
    Sched->>DB: Query unassigned leads (excluding DoNotContact, ordered by score DESC)
    DB-->>Sched: Return top 50 qualified leads
    Sched->>DB: Create LeadAssignment records (status="pending", assigned_to=sales_1)
    Sched-->>Mgr: Notification: 50 leads assigned
    
    Rep->>Rep: Log in and navigate to /leads/?assigned_to=me
    Rep->>Rep: Click 1-Click Copy on author email
    Rep->>Rep: Review AI Sales Pitch Hook
    Rep->>DB: Update stage to "in_progress" ➔ "contacted" ➔ "meeting_booked"
    DB-->>Mgr: Real-time dashboard KPI update
```
