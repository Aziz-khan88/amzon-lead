# ⚙️ Setup & Installation Guide

This guide provides step-by-step instructions for installing, configuring, and running the **Book Trailer Lead Finder** application in a local development or staging environment.

---

## 📋 System Prerequisites

* **Operating System:** Windows 10/11, macOS, or Linux (Ubuntu 22.04+ recommended)
* **Python Version:** Python `3.11`, `3.12`, or `3.14` (64-bit)
* **Database:** SQLite (built-in default) or PostgreSQL 14+
* **Package Manager:** `pip` (bundled with Python)
* **Git:** Version 2.30+ installed and configured

---

## 🛠️ Step-by-Step Installation

### Step 1: Clone the Repository
Clone the codebase to your local disk:

```powershell
git clone git@github.com:Aziz-khan88/amzon-lead.git booktrailer_leads
cd booktrailer_leads
```

---

### Step 2: Set Up Virtual Environment

#### On Windows (PowerShell):
```powershell
# Create virtual environment
python -m venv .venv

# Enable script execution if blocked by PowerShell policy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

# Activate the virtual environment
.\.venv\Scripts\Activate.ps1
```

#### On Linux / macOS (Bash):
```bash
# Create virtual environment
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate
```

---

### Step 3: Install Required Dependencies
Install the pinned application dependencies:

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

*(Optional)* If you plan to run automated browser visual verification tests:
```powershell
pip install playwright
playwright install chromium
```

---

### Step 4: Configure Environment Variables
Copy the template configuration file:

```powershell
copy .env.example .env
```

Open `.env` in your text editor and configure key parameters:

```env
# Application Settings
DEBUG=True
SECRET_KEY=django-insecure-leadfinder-development-key-change-in-prod
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Optional Database URL (Default is SQLite db.sqlite3)
# DATABASE_URL=postgres://user:password@localhost:5432/booktrailer_leads

# Optional AI & Search API Keys (DDGS is free and requires no key)
GROQ_API_KEY=your_groq_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
BRAVE_API_KEY=your_brave_api_key_here
YOUTUBE_API_KEY=your_youtube_data_api_key_here

# Scheduler Configuration
APP_MAX_SOCIAL_CONTACT_PAGES=5
APP_SCHEDULED_TASK_LEASE_SECONDS=21600
```

---

### Step 5: Run Database Migrations
Initialize the database tables:

```powershell
python manage.py migrate
```

---

### Step 6: Create Superuser & Team Accounts
You can create an administrator account using standard Django CLI:

```powershell
python manage.py createsuperuser --username admin --email admin@example.com
```

Or run the automated bootstrap script to provision standard demo roles (`admin`, `manager`, `sales`):

```powershell
python manage.py bootstrap_superadmin
```

---

### Step 7: Load Production Lead Datasets

To populate the database with the pre-verified lead workbooks:

```powershell
# Import the primary leads dataset
python manage.py import_excel_leads "E:\yt-video\leads data.xlsx"

# Import the secondary enriched dataset (includes automatic column-shift safeguards)
python manage.py import_excel_leads "E:\yt-video\leads dev-ali.xlsx"
```

This will ingest and verify over **1,840 books and leads**, complete with publication dates, author profiles, and contact evidence records.

---

### Step 8: Launch the Development Server
Start the Django development server:

```powershell
python manage.py runserver 0.0.0.0:3005
```

Navigate to:
* **Leads Dashboard:** [http://127.0.0.1:3005/leads/](http://127.0.0.1:3005/leads/)
* **Admin Portal:** [http://127.0.0.1:3005/admin/](http://127.0.0.1:3005/admin/)
* **ISBN Search:** [http://127.0.0.1:3005/isbn-search/](http://127.0.0.1:3005/isbn-search/)

---

### Step 9: Run Background Scheduler (Optional Worker)
To execute recurring lead discovery tasks automatically:

```powershell
# Run a one-time scheduler check
python manage.py run_scheduler_loop

# Or run as a long-lived polling worker
python manage.py run_scheduler_loop --daemon --check-interval=60
```

---

## 🧪 Verification & Testing

Verify that your local environment is correctly configured by executing the test suite:

```powershell
# Execute full Pytest test suite (281 tests)
python -m pytest leadfinder/tests

# Check Django system checks
python manage.py check
```

Expected output:
```text
======================= 281 passed in 123.53s =======================
```

---

## 🔍 Troubleshooting & FAQs

### Q: `Activate.ps1 cannot be loaded because running scripts is disabled on this system`
**Fix:** Run PowerShell as Administrator and execute:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Q: `OperationalError: database is locked` (SQLite)
**Fix:** Ensure no background process or interactive Python shell is holding an exclusive transaction. If persistent, restart the dev server. For high concurrency, configure PostgreSQL via `DATABASE_URL`.

### Q: `ModuleNotFoundError: No module named 'tldextract'`
**Fix:** Ensure your virtual environment is active (`(.venv)` prefix in terminal) and re-run:
```powershell
pip install -r requirements.txt
```

### Q: Dropdown menus or table styles look outdated in my browser
**Fix:** Perform a hard refresh using `Ctrl + F5` (or `Cmd + Shift + R` on macOS). All static asset references include cache-busting version tags (`?v=3.0`).
