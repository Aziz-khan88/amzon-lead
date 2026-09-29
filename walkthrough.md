# Book Trailer Lead Finder: Workflow and Scheduler Guide

The application runs an evidence-first research pipeline for children's-book author leads. Every workflow produces normal `ResearchRun`, `Book`, `Lead`, and `Evidence` records, so UI runs, commands, retries, and exports share the same audit trail.

## End-to-end workflow

1. **Discover** books through keyword research, BookLife, CSV import, or ISBN/ASIN lookup.
2. **Enrich** each accepted book with an author profile, official-site/contact-page signals, public social links, and video evidence.
3. **Crawl public bio links** from an identity-matched social profile once when they point to supported Linktree, Carrd, Substack, or known author-site pages. The crawler follows `robots.txt`, obeys the configured delay, caps page size and redirects, and never bypasses access controls.
4. **Extract contacts** from visible text, `mailto:` and `tel:` links, HTML entities, `[at]`/`[dot]` text, URL encoding, and Cloudflare email-protection markup. Every candidate retains its exact source URL.
5. **Verify and score** syntax, contact-source trust, author identity, role, optional DNS/SMTP delivery evidence, and corroboration. The result is `verified`, `not_verified`, or `other` with a 0–100 evidence score.
6. **Create a sales brief** and apply the quality gate. Leads still need human review before outreach.
7. **Review and export** filtered leads from `/leads/`, the run detail, or the CSV/XLSX export commands.

Verification is evidence-based, not a claim of certainty. No public crawler can prove mailbox ownership or guarantee “10/10 accuracy”; catch-all mailboxes, blocked SMTP, changed pages, and identity ambiguity remain possible. Use the evidence links, warnings, and `do_not_contact` state when deciding whether to contact someone.

## Scheduled lead hunts

Create a task at `/scheduled-tasks/new/` with:

- A focused keyword and available web-search provider.
- A daily, interval, weekly, or specific-days cadence. Weekly schedules use exactly one weekday; select **specific days** for multiple weekdays.
- A target of 25, 50, 100, or 200 verified contactable leads.
- A verified-email-only or verified-email-or-phone requirement.
- New-book-only deduplication and optional network email checks.

The application calculates `next_run_at` in the configured `TIME_ZONE`. Each execution has a bounded candidate pool of three times its requested lead target, up to `APP_SCHEDULED_MAX_BOOKS` (default `700`), and stops early when it reaches the target.

## Run the scheduler

Run all due tasks one time:

```powershell
python manage.py run_scheduler_loop
```

Keep a worker running and check every minute:

```powershell
python manage.py run_scheduler_loop --daemon --check-interval=60
```

Run exactly one scheduler service under a process manager in production. Claims are atomic, so a scheduler tick and **Run now** cannot start the same task simultaneously. A task left in `running` state by a crashed process may be reclaimed only after `APP_SCHEDULED_TASK_LEASE_SECONDS` (default `21600` seconds); choose a lease longer than the longest expected run. Pause blocks future claims but allows an already-running job to finish safely.

Each scheduled execution records its linked run, duplicate skips, target progress, totals, errors, and next occurrence. Failed tasks remain visible and can run again at their next occurrence or by using **Run now** after resolving the underlying issue.

## Operational verification

From the `booktrailer_leads` directory, run:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest leadfinder/tests -q
```

The test suite covers discovery helpers, extraction, source verification, contact classification, exports, UI routes, scheduled-task creation, duplicate claims, stale-lease recovery, and scheduler command behavior.
