from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import traceback

import django


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Process one imported CSV ResearchRun only.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", default="ddgs")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "booktrailer_leads.settings")
    django.setup()

    from django.core.management import call_command
    from leadfinder.models import Lead, ResearchRun
    from leadfinder.services.export.csv_export import export_leads_to_file
    from leadfinder.services.pipeline.process_book import process_book

    status_path = Path(args.status)
    output_path = Path(args.output)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def get_run():
        return ResearchRun.objects.get(id=args.run_id)

    def write_status(state: str, index: int, total: int, message: str = "", exit_code: int = 0) -> None:
        run = get_run()
        payload = {
            "state": state,
            "mode": "batch_001_only",
            "provider": args.provider,
            "run_id": str(run.id),
            "current_index": index,
            "total": total,
            "completed_books": run.books.filter(source_raw_json__processing_status="completed").count(),
            "failed_books": run.books.filter(source_raw_json__processing_status="failed").count(),
            "processing_books": run.books.filter(source_raw_json__processing_status="processing").count(),
            "lead_count": Lead.objects.filter(book__research_run=run).count(),
            "message": message[:500],
            "exit_code": exit_code,
            "output": str(output_path),
        }
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run = get_run()
    settings = dict(run.settings_json or {})
    settings["enrichment_provider"] = args.provider
    settings["run_video_search"] = False
    run.settings_json = settings
    run.save(update_fields=["settings_json", "updated_at"])
    run.mark_running()

    books = list(run.books.order_by("created_at", "id"))
    write_status("running", 0, len(books), "Starting batch 001 only worker")

    try:
        for index, book in enumerate(books, start=1):
            if Lead.objects.filter(book=book).exists():
                raw = book.source_raw_json if isinstance(book.source_raw_json, dict) else {}
                raw["processing_status"] = "completed"
                raw["batch_one_position"] = index
                book.source_raw_json = raw
                book.save(update_fields=["source_raw_json", "updated_at"])
                write_status("running", index, len(books), f"Skipped existing lead for {book.title}")
                continue

            raw = book.source_raw_json if isinstance(book.source_raw_json, dict) else {}
            raw["processing_status"] = "processing"
            raw["batch_one_position"] = index
            book.source_raw_json = raw
            book.save(update_fields=["source_raw_json", "updated_at"])
            write_status("running", index, len(books), f"Processing {book.title}")

            try:
                process_book(
                    book,
                    run_video_search=False,
                    run_ai_extraction=bool(settings.get("run_groq_ai_extraction", True)),
                )
                book.refresh_from_db()
                raw = book.source_raw_json if isinstance(book.source_raw_json, dict) else {}
                raw["processing_status"] = "completed"
                raw["batch_one_position"] = index
                book.source_raw_json = raw
                book.save(update_fields=["source_raw_json", "updated_at"])
                print(f"BOOK_DONE {index}/{len(books)} {book.title[:120]}", flush=True)
            except Exception as exc:
                try:
                    book.refresh_from_db()
                except Exception:
                    pass
                raw = book.source_raw_json if isinstance(book.source_raw_json, dict) else {}
                raw["processing_status"] = "failed"
                raw["batch_one_position"] = index
                raw.setdefault("book_processing_errors", []).append(str(exc))
                book.source_raw_json = raw
                book.save(update_fields=["source_raw_json", "updated_at"])
                print(f"BOOK_FAILED {index}/{len(books)} {book.title[:120]} :: {exc}", flush=True)

            write_status("running", index, len(books), f"Finished row {index}")

        call_command("sanitize_contact_sources")
        queryset = Lead.objects.filter(book__research_run=run).order_by("-lead_score", "-created_at")
        exported = export_leads_to_file(queryset, str(output_path))
        run.mark_completed()
        write_status("completed", len(books), len(books), f"Batch 001 complete; exported {exported} leads")
        print(f"BATCH_001_COMPLETE exported={exported} output={output_path}", flush=True)
        return 0
    except Exception as exc:
        traceback.print_exc()
        try:
            run.mark_failed(str(exc))
        except Exception:
            pass
        write_status("failed", 0, len(books), str(exc), exit_code=1)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
