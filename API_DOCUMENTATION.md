# 🔌 API & Endpoint Documentation

This document provides complete documentation for the REST API endpoints, JWT authentication mechanisms, internal JSON APIs, and programmatic interfaces available in the **Book Trailer Lead Finder** platform.

---

## 1. Authentication & Security

The platform supports dual authentication methods:
1. **JWT Authentication:** Bearer tokens for external API consumers, automated crawlers, or headless integrations.
2. **Session Authentication:** Standard Django sessions with CSRF protection for browser-based operations.

### Base Headers
For programmatic requests using JWT:
```http
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json
```

---

## 2. Authentication Endpoints

### 2.1 Obtain JWT Pair
Returns a JSON Web Token pair (access and refresh) along with the user's role and profile details.

* **Endpoint:** `POST /api/auth/token/`
* **Access:** Public (Rate-limited)
* **Request Body:**
```json
{
  "username": "sales_rep_1",
  "password": "SecurePassword123!"
}
```

* **Success Response (`200 OK`):**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 4,
    "username": "sales_rep_1",
    "email": "sales1@example.com",
    "role": "sales",
    "assigned_leads_count": 48
  }
}
```

* **Error Response (`401 Unauthorized`):**
```json
{
  "detail": "No active account found with the given credentials"
}
```

---

### 2.2 Refresh JWT Access Token
Generates a fresh access token using a valid refresh token.

* **Endpoint:** `POST /api/auth/token/refresh/`
* **Request Body:**
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

* **Success Response (`200 OK`):**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

---

## 3. ISBN Search & Book Intelligence API

The ISBN intelligence suite provides checksum validation, ASIN conversion, metadata reconciliation, and dynamic vector barcode generation.

### 3.1 Analyze ISBN Identifier
Validates any input string as ISBN-10, ISBN-13, or Amazon ASIN.

* **Endpoint:** `POST /isbn-search/analyze/`
* **Access:** Authenticated
* **Request Body:**
```json
{
  "identifier": "9780545162074"
}
```

* **Success Response (`200 OK`):**
```json
{
  "is_valid": true,
  "canonical_isbn13": "9780545162074",
  "canonical_isbn10": "0545162076",
  "asin": "0545162076",
  "checksum_valid": true,
  "detected_format": "ISBN-13",
  "barcode_url": "/isbn-search/barcode/9780545162074.svg"
}
```

---

### 3.2 ISBN Metadata Multi-Source Lookup
Performs real-time reconciliation across Open Library, Google Books, and public Amazon indices.

* **Endpoint:** `POST /isbn-search/lookup/`
* **Access:** Authenticated
* **Request Body:**
```json
{
  "isbn": "9780545162074"
}
```

* **Success Response (`200 OK`):**
```json
{
  "status": "success",
  "title": "Wonder",
  "author": "R. J. Palacio",
  "publication_date": "2012-02-14",
  "publisher": "Alfred A. Knopf",
  "pages": 315,
  "categories": ["Juvenile Fiction", "Social Themes"],
  "cover_image_url": "https://covers.openlibrary.org/b/id/8225261-L.jpg",
  "sources": [
    { "provider": "open_library", "confidence": 0.95 },
    { "provider": "google_books", "confidence": 0.92 }
  ]
}
```

---

### 3.3 Dynamic SVG Barcode Generator
Renders an official vector EAN-13 barcode for verified books.

* **Endpoint:** `GET /isbn-search/barcode/<str:identifier>.svg`
* **Access:** Public / Cache-enabled
* **Response:** `image/svg+xml`

---

## 4. Research Runs & Live Agent Monitoring

### 4.1 Live Agent Execution Status
Returns real-time progress of an active research run, current pipeline phase, and discovered items.

* **Endpoint:** `GET /runs/<uuid:pk>/status/`
* **Access:** Authenticated
* **Success Response (`200 OK`):**
```json
{
  "run_id": "4e76a6f1-4db8-406c-8515-56586326e5a4",
  "status": "running",
  "active_agent": "Harvester",
  "progress_percent": 68,
  "books_discovered": 25,
  "contacts_extracted": 34,
  "current_activity": "Inspecting author domain: https://rjpalacio.com",
  "started_at": "2026-09-30T01:10:00Z",
  "elapsed_seconds": 45
}
```

---

### 4.2 Terminate Research Run
Safely requests termination of a running research process.

* **Endpoint:** `POST /runs/<uuid:pk>/stop/`
* **Access:** Manager / Superadmin
* **Request Body:**
```json
{
  "reason": "Target lead quota achieved early"
}
```
* **Success Response (`200 OK`):**
```json
{
  "status": "canceled",
  "message": "Research run successfully stopped. Saved data has been preserved."
}
```

---

## 5. Lead Pipeline & Workflow Actions

### 5.1 Lead Lifecycle Action
Applies an action to an individual lead (e.g. suppression or deletion).

* **Endpoint:** `POST /leads/<uuid:pk>/<str:action>/`
* **Allowed Actions:** `do_not_contact`, `delete`
* **Access:** Manager / Superadmin
* **Success Response (`200 OK`):**
```json
{
  "success": true,
  "lead_id": "8c30b3e3-fbc6-441b-a0aa-4f177b957b05",
  "action": "do_not_contact",
  "message": "Lead and associated author emails added to global suppression list."
}
```

---

### 5.2 Bulk Lead Operations
Applies changes to multiple leads simultaneously.

* **Endpoint:** `POST /leads/bulk-action/`
* **Access:** Manager / Superadmin
* **Request Body:**
```json
{
  "lead_ids": [
    "8c30b3e3-fbc6-441b-a0aa-4f177b957b05",
    "e825f997-62ec-440c-9ec5-44088a5515bd"
  ],
  "action": "assign_rep",
  "assigned_user_id": 4
}
```

* **Success Response (`200 OK`):**
```json
{
  "success": true,
  "affected_count": 2,
  "message": "2 leads successfully reassigned to sales_rep_1."
}
```

---

### 5.3 Update Lead Assignment Stage
Transitions a lead through the sales pipeline.

* **Endpoint:** `POST /lead-assignments/<uuid:pk>/update/`
* **Access:** Assigned Sales Rep / Manager / Superadmin
* **Request Body:**
```json
{
  "status": "meeting_booked",
  "notes": "Author interested in 30-second 2D animated trailer for Halloween release."
}
```

* **Success Response (`200 OK`):**
```json
{
  "success": true,
  "assignment_id": "b3e3441b-fbc6-441b-a0aa-4f177b957b05",
  "current_status": "meeting_booked",
  "updated_at": "2026-09-30T01:15:00Z"
}
```

---

## 6. Scheduled Hunts API

### 6.1 Trigger Scheduled Task Now
Immediately runs a scheduled research task out-of-band without waiting for its cron interval.

* **Endpoint:** `POST /scheduled-tasks/<uuid:pk>/run-now/`
* **Access:** Manager / Superadmin
* **Success Response (`200 OK`):**
```json
{
  "success": true,
  "task_id": "11114e23-2323-4391-bb43-4b616e14a449",
  "new_run_id": "c10c1603-be2f-4da3-ad46-d84b9b9e91a8",
  "message": "Lead hunt started successfully."
}
```

---

## 7. Data Export Endpoints

### 7.1 Export Verified Leads CSV
Streams filtered leads directly into CSV format.

* **Endpoint:** `GET /export/leads.csv`
* **Access:** Authenticated
* **Query Parameters:**
  * `verification_status` (e.g. `verified`, `needs_review`)
  * `video_status` (e.g. `no_public_video_found`)
  * `min_score` (e.g. `75`)
* **Response Headers:**
```http
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="verified_booktrailer_leads_20260930.csv"
```

---

### 7.2 Export Formatted Excel Workbook
Generates a multi-sheet formatted `.xlsx` workbook complete with lead summaries, evidence links, and contact breakdown.

* **Endpoint:** `GET /export/leads.xlsx`
* **Access:** Authenticated
* **Response Headers:**
```http
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename="booktrailer_leads_export_20260930.xlsx"
```

---

## 8. HTTP Status Codes & Error Handling

Standard HTTP response codes are returned:

| Code | Meaning | Typical Scenario |
| :---: | :--- | :--- |
| `200` | OK | Successful request execution. |
| `201` | Created | Resource successfully created. |
| `400` | Bad Request | Missing required parameters or invalid JSON body. |
| `401` | Unauthorized | Missing or expired JWT / Session. |
| `403` | Forbidden | Insufficient role permissions (e.g. sales rep accessing superadmin actions). |
| `404` | Not Found | Lead, book, or run UUID not found. |
| `429` | Too Many Requests | Rate limit exceeded on authentication or search lookup. |
| `500` | Server Error | Internal unhandled exception. |

Standard JSON error response:
```json
{
  "error": true,
  "code": "PERMISSION_DENIED",
  "message": "You do not have permission to delete leads."
}
```
