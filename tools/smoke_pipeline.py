"""Reproduce the parallel smoke run and capture full failure tracebacks."""
import os, sys, time, threading, traceback

BASE = os.path.abspath(os.path.dirname(__file__) + "/..")
sys.path.insert(0, BASE)
DB = os.path.join(BASE, ".cache", "test_repro.sqlite3")
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(DB + suffix)
    except OSError:
        pass
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["DJANGO_SETTINGS_MODULE"] = "booktrailer_leads.settings"
os.environ["GROQ_API_KEY"] = ""  # force deterministic fallbacks
os.environ["APP_WIKIDATA_AUTHOR_LOOKUP"] = "0"  # keep the smoke run offline

import django
django.setup()

from django.core.management import call_command
call_command("migrate", run_syncdb=True, verbosity=0)

from django.db import connection
from leadfinder.models import Book, ResearchRun
from leadfinder.services.ai.schemas import BookClassification, ContactExtraction
from leadfinder.services.pipeline import run_research as rr
from leadfinder.services.pipeline import process_book as pb


class FakeProvider:
    provider_name = "fake"

    def search(self, query, max_results=5):
        time.sleep(0.2)
        return []


real_process_book = rr.process_book
_seen_threads = set()
_tb_lock = threading.Lock()


def traced_process_book(*args, **kwargs):
    tid = threading.get_ident()
    if tid not in _seen_threads:
        _seen_threads.add(tid)
        with connection.cursor() as cur:
            cur.execute("PRAGMA busy_timeout;")
            bt = cur.fetchone()[0]
            cur.execute("PRAGMA journal_mode;")
            jm = cur.fetchone()[0]
        print(f"[thread {tid}] busy_timeout={bt} journal_mode={jm}", flush=True)
    try:
        return real_process_book(*args, **kwargs)
    except Exception:
        with _tb_lock:
            traceback.print_exc()
        raise


pb.classify_book = lambda *a, **k: BookClassification(
    is_childrens_book=True, is_picture_or_illustrated_book=True, confidence=0.9, reason="mock"
)
pb.extract_contact_data = lambda *a, **k: ContactExtraction(confidence=0.2)
pb.get_search_provider = lambda *a, **k: FakeProvider()
pb.search_youtube_api = lambda *a, **k: (time.sleep(0.2), [])[1]
pb.harvest_social_profiles = lambda *a, **k: {}
rr.process_book = traced_process_book

run = ResearchRun.objects.create(
    keyword="smoke",
    source_provider="csv",
    max_books=3,
    settings_json={"run_video_search": True, "run_groq_ai_extraction": False, "verify_email_mx": False},
)
for i in range(3):
    Book.objects.create(
        research_run=run,
        title=f"Smoke Book {i}",
        author_name=f"Smoke Author {i}",
        normalized_key=f"smoke-{i}",
        source_provider="csv",
    )

t0 = time.monotonic()
rr.run_research_pipeline(run.id)
elapsed = time.monotonic() - t0

completed = 0
for b in Book.objects.filter(research_run=run):
    raw = b.source_raw_json or {}
    status = raw.get("processing_status")
    completed += status == "completed"
    print(f"{b.title}: {status} | {raw.get('processing_detail', '')[:120]}")
print(f"elapsed={elapsed:.2f}s completed={completed}/3")
