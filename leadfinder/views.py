from __future__ import annotations

import csv
import io
import importlib.util
import os
import re
import threading
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import close_old_connections
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import BookLifeRunForm, CSVImportForm, LeadFilterForm, ResearchRunForm, ISBNSearchForm
from .models import Book, Evidence, Lead, ResearchRun
from .services.amazon.amazon_url_parser import extract_asin, is_amazon_url, normalize_amazon_book_url
from .services.booklife import BOOKLIFE_CATEGORIES, grouped_booklife_categories
from .services.books.isbn_intelligence import analyze_identifier, generate_barcode_svg
from .services.export.csv_export import export_leads_response, export_leads_xlsx
from .services.pipeline.quality_gate import can_approve_lead, has_verified_contact_source
from .services.pipeline.source_audit import is_catalog_or_platform_source
from .services.pipeline.run_research import keyword_suggestions, run_research_pipeline
from .services.pipeline.process_book import process_book
from .utils.normalize import normalized_book_key



HEADER_ALIASES = {
    "title": ["title", "book_title", "name", "book name"],
    "author_name": ["author", "author_name"],
    "illustrator_name": ["illustrator", "illustrator_name"],
    "amazon_book_url": ["amazon_url", "amazon_book_url", "link", "amazon product url"],
    "asin": ["asin"],
    "category": ["category"],
    "review_count": ["review_count", "no_of_ratings"],
    "rating": ["rating", "rating_out_of_5"],
    "publisher": ["publisher"],
    "publication_date": ["publication_date"],
    "cover_image_url": ["cover_image_url"],
}


CONTACTABLE_Q = (
    Q(public_email__gt="")
    | Q(public_phone__gt="")
    | Q(representation_email__gt="")
    | Q(publicist_email__gt="")
    | Q(author_profile__contact_page_url__gt="")
)


def _contactable_queryset(queryset):
    return queryset.filter(CONTACTABLE_Q)


def _start_research_pipeline(research_run_id) -> None:
    def target() -> None:
        close_old_connections()
        try:
            run_research_pipeline(research_run_id)
        except Exception:
            pass
        finally:
            close_old_connections()

    threading.Thread(target=target, name=f"research-run-{research_run_id}", daemon=True).start()


def _value(row: dict, field: str) -> str:
    for alias in HEADER_ALIASES[field]:
        if alias in row and row[alias]:
            return str(row[alias]).strip()
    return ""


def _int_or_none(value: str):
    try:
        cleaned = str(value).replace(",", "").strip()
        if not cleaned:
            return None
        if "." in cleaned:
            whole, fraction = cleaned.split(".", 1)
            significant_fraction = fraction.rstrip("0")
            if whole.isdigit() and len(significant_fraction) >= 3:
                return int(round(float(cleaned) * 1000))
        return int(float(cleaned))
    except ValueError:
        return None


def _decimal_or_none(value: str):
    try:
        raw = str(value).strip()
        return Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if raw else None
    except (InvalidOperation, ValueError):
        return None


def import_books_from_rows(rows: list[dict], run: ResearchRun, source_label: str = "uploaded_csv/manual") -> int:
    count = 0
    for raw in rows:
        row = {str(k).strip().lower(): (v or "").strip() for k, v in raw.items()}
        title = _value(row, "title")
        author_name = _value(row, "author_name")
        if not title or not author_name:
            continue
        amazon_url = _value(row, "amazon_book_url")
        asin = (_value(row, "asin") or extract_asin(amazon_url) or "").upper()
        if asin and not amazon_url:
            amazon_url = normalize_amazon_book_url(f"https://www.amazon.com/dp/{asin}", os.getenv("AMAZON_ASSOCIATE_TAG") or None)
        elif amazon_url and asin:
            amazon_url = normalize_amazon_book_url(amazon_url, os.getenv("AMAZON_ASSOCIATE_TAG") or None)
        book = Book.objects.create(
            research_run=run,
            title=title,
            author_name=author_name,
            illustrator_name=_value(row, "illustrator_name"),
            asin=asin,
            amazon_book_url=amazon_url,
            amazon_source_url=amazon_url or source_label,
            category=_value(row, "category"),
            review_count=_int_or_none(_value(row, "review_count")),
            rating=_decimal_or_none(_value(row, "rating")),
            publisher=_value(row, "publisher"),
            publication_date=_value(row, "publication_date"),
            cover_image_url=_value(row, "cover_image_url"),
            normalized_key=normalized_book_key(title, author_name, asin),
            book_data_confidence=0.9,
            source_provider=run.source_provider,
            source_raw_json={"source": source_label},
        )
        if amazon_url:
            Evidence.objects.create(
                book=book,
                evidence_type="manual" if run.source_provider == "manual" else "amazon_search_result",
                field_name="amazon_book_url",
                field_value=amazon_url,
                source_url=source_label,
                confidence=0.9,
                is_primary=True,
            )
        count += 1
    return count


def dashboard(request):
    leads = Lead.objects.all()
    failed_runs = ResearchRun.objects.filter(status="failed")
    context = {
        "total_leads": leads.count(),
        "hot_leads": leads.filter(lead_tier="hot").count(),
        "warm_leads": leads.filter(lead_tier="warm").count(),
        "cold_leads": leads.filter(lead_tier="cold").count(),
        "rejected_leads": leads.filter(Q(lead_tier="rejected") | Q(manual_review_status="rejected")).count(),
        "public_emails": leads.exclude(public_email="").count(),
        "amazon_urls": Book.objects.exclude(amazon_book_url="").count(),
        "no_public_video_found": leads.filter(video_status="no_public_video_found").count(),
        "video_found": leads.filter(video_status__in=["found_trailer", "found_animated_video", "found_read_aloud_only"]).count(),
        "needs_review": leads.filter(manual_review_status="needs_review").count(),
        "approved": leads.filter(manual_review_status="approved").count(),
        "do_not_contact": leads.filter(do_not_contact=True).count(),
        "failed_runs": failed_runs.count(),
        "latest_errors": failed_runs.exclude(error_message="").order_by("-completed_at", "-created_at")[:3],
        "latest_runs": ResearchRun.objects.order_by("-created_at")[:8],
    }
    return render(request, "leadfinder/dashboard.html", context)


@require_POST
def delete_rejected_leads(request):
    deleted_count, _ = Lead.objects.filter(
        Q(lead_tier="rejected") | Q(manual_review_status="rejected")
    ).delete()
    messages.success(request, f"Successfully deleted {deleted_count} rejected leads.")
    return redirect("leadfinder:dashboard")



def run_new(request):
    if request.method == "POST":
        form = ResearchRunForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["source_provider"] == "csv":
                messages.info(request, "CSV runs start from the import screen.")
                return redirect("leadfinder:import_csv")
            run = ResearchRun.objects.create(
                keyword=form.cleaned_data["keyword"],
                source_provider=form.cleaned_data["source_provider"],
                marketplace=form.cleaned_data["marketplace"],
                max_books=form.cleaned_data["max_books"],
                settings_json={
                    "require_amazon_url": form.cleaned_data["require_amazon_url"],
                    "require_public_email": form.cleaned_data["require_public_email"],
                    "include_social_only_leads": form.cleaned_data["include_social_only_leads"],
                    "run_video_search": form.cleaned_data["run_video_search"],
                    "run_groq_ai_extraction": form.cleaned_data["run_groq_ai_extraction"],
                    "location_preference": form.cleaned_data["location_preference"],
                },
            )
            if run.source_provider != "csv":
                _start_research_pipeline(run.id)
            messages.success(request, "Research run created. Search is running in the background.")
            return redirect("leadfinder:run_detail", pk=run.id)
    else:
        form = ResearchRunForm()
    return render(request, "leadfinder/run_new.html", {"form": form, "keyword_suggestions": keyword_suggestions()})


def booklife_run(request):
    category_labels = {category.slug or "all": category.label for category in BOOKLIFE_CATEGORIES}
    if request.method == "POST":
        form = BookLifeRunForm(request.POST)
        if form.is_valid():
            categories = form.cleaned_data["booklife_categories"]
            labels = [category_labels.get(slug, slug) for slug in categories]
            keyword = "BookLife: " + ", ".join(labels[:3])
            if len(labels) > 3:
                keyword = f"{keyword} + {len(labels) - 3} more"
            run = ResearchRun.objects.create(
                keyword=keyword,
                source_provider="booklife",
                marketplace="US",
                max_books=form.cleaned_data["max_books"],
                settings_json={
                    "booklife_categories": categories,
                    "booklife_category_labels": labels,
                    "booklife_age_filter": form.cleaned_data["age_filter"],
                    "enrichment_provider": form.cleaned_data["enrichment_provider"],
                    "require_amazon_url": False,
                    "require_public_email": form.cleaned_data["require_public_email"],
                    "include_social_only_leads": form.cleaned_data["include_social_only_leads"],
                    "run_video_search": form.cleaned_data["run_video_search"],
                    "run_groq_ai_extraction": form.cleaned_data["run_groq_ai_extraction"],
                },
            )
            _start_research_pipeline(run.id)
            messages.success(request, "BookLife runner created. Discovery and enrichment are running in the background.")
            return redirect("leadfinder:run_detail", pk=run.id)
    else:
        form = BookLifeRunForm(initial={"booklife_categories": ["all"]})
    return render(
        request,
        "leadfinder/booklife_run.html",
        {
            "form": form,
            "category_groups": grouped_booklife_categories(),
            "selected_categories": form["booklife_categories"].value() or ["all"],
        },
    )


def run_list(request):
    runs = ResearchRun.objects.annotate(total_books=Count("books"), total_leads=Count("books__leads")).order_by("-created_at")
    
    total_count = runs.count()
    completed_count = runs.filter(status="completed").count()
    running_count = runs.filter(status__in=["pending", "running"]).count()
    failed_count = runs.filter(status__in=["failed", "canceled"]).count()
    
    return render(
        request, 
        "leadfinder/run_list.html", 
        {
            "runs": runs,
            "stats": {
                "total": total_count,
                "completed": completed_count,
                "running": running_count,
                "failed": failed_count,
            }
        }
    )


def run_detail(request, pk):
    run = get_object_or_404(ResearchRun, pk=pk)
    books = list(run.books.prefetch_related("leads").all())
    leads = list(Lead.objects.filter(book__research_run=run).select_related("book", "author_profile"))
    search_logs = list(run.search_logs.annotate(
        total_results=Count("results"),
        amazon_results=Count("results", filter=Q(results__classification="amazon_book")),
    ).order_by("created_at"))
    no_search_results = bool(search_logs) and all(log.total_results == 0 for log in search_logs)
    lead_checks = []
    for lead in leads:
        passed, errors = can_approve_lead(
            lead,
            allow_incomplete_video=not bool(run.settings_json.get("run_video_search", True)),
        )
        lead_checks.append({"lead": lead, "passed": passed, "errors": errors})
    book_errors = [
        {
            "book": book,
            "errors": (book.source_raw_json or {}).get("book_processing_errors", []),
        }
        for book in books
        if (book.source_raw_json or {}).get("book_processing_errors")
    ]
    return render(
        request,
        "leadfinder/run_detail.html",
        {
            "run": run,
            "books": books,
            "leads": leads,
            "search_logs": search_logs,
            "lead_checks": lead_checks,
            "book_errors": book_errors,
            "no_search_results": no_search_results,
        },
    )


def run_agent_status(request, pk):
    run = get_object_or_404(ResearchRun, pk=pk)
    books = run.books.all()
    total_books = books.count()
    completed_books = 0
    for book in books:
        status = (book.source_raw_json or {}).get("processing_status", "")
        if status in {"completed", "failed"}:
            completed_books += 1
            
    progress = 0
    if run.status == "completed":
        progress = 100
    elif run.status == "failed":
        progress = 100
    elif total_books > 0:
        progress = int((completed_books / total_books) * 100)
        if progress >= 100 and run.status == "running":
            progress = 99
            
    discovered_count = total_books
    verified_leads_count = Lead.objects.filter(book__research_run=run).exclude(Q(lead_tier="rejected") | Q(manual_review_status="rejected")).count()
    
    thoughts = run.agent_thoughts.order_by("created_at")
    recent_thoughts = [
        {
            "agent_name": t.agent_name,
            "message": t.message,
            "created_at": t.created_at.strftime("%I:%M:%S %p"),
        }
        for t in thoughts
    ]
    
    active_agent = "Scout"
    if run.status in {"completed", "failed", "canceled"}:
        active_agent = "None"
    elif recent_thoughts:
        active_agent = recent_thoughts[-1]["agent_name"]
        
    return JsonResponse({
        "status": run.get_status_display() if hasattr(run, "get_status_display") else run.status,
        "run_status_raw": run.status,
        "progress": progress,
        "discovered_count": discovered_count,
        "verified_leads_count": verified_leads_count,
        "active_agent": active_agent,
        "thoughts": recent_thoughts,
    })


def import_csv(request):
    preview = []
    if request.method == "POST":
        form = CSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            content = form.cleaned_data["csv_file"].read().decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(content)))
            if "preview" in request.POST:
                preview = rows[:20]
            else:
                run = ResearchRun.objects.create(
                    keyword="CSV import",
                    source_provider="csv",
                    max_books=max(len(rows), 1),
                    settings_json={
                        "require_public_email": False,
                        "run_video_search": form.cleaned_data["run_video_search"],
                        "run_groq_ai_extraction": form.cleaned_data["run_groq_ai_extraction"],
                    },
                )
                imported = import_books_from_rows(rows, run)
                run.max_books = imported
                run.save(update_fields=["max_books"])
                _start_research_pipeline(run.id)
                messages.success(request, f"Imported {imported} books. Enrichment is running in the background.")
                return redirect("leadfinder:run_detail", pk=run.id)
    else:
        form = CSVImportForm()
    return render(request, "leadfinder/import_csv.html", {"form": form, "preview": preview})


def lead_list(request):
    form = LeadFilterForm(request.GET or None)
    leads = Lead.objects.select_related("book", "author_profile")

    explicitly_showing_excluded = (
        request.GET.get("tier") == "rejected"
        or request.GET.get("manual_review_status") in {"rejected", "do_not_contact"}
        or request.GET.get("do_not_contact", "").lower() in {"1", "true", "on", "yes"}
    )
    if not explicitly_showing_excluded:
        leads = leads.exclude(lead_tier="rejected").exclude(
            Q(manual_review_status__in=["rejected", "do_not_contact"]) | Q(do_not_contact=True)
        )
    
    # Apply standard filters
    if form.is_valid():
        cd = form.cleaned_data

        # Keyword Search
        if cd.get("q"):
            q_term = cd["q"].strip()
            leads = leads.filter(
                Q(book__title__icontains=q_term) |
                Q(book__author_name__icontains=q_term) |
                Q(public_email__icontains=q_term) |
                Q(representation_email__icontains=q_term) |
                Q(publicist_email__icontains=q_term)
            )
            
        if cd.get("valid_only"):
            leads = _contactable_queryset(leads.exclude(lead_tier__in=["cold", "rejected"]).exclude(book__amazon_book_url=""))
        if cd.get("tier"):
            leads = leads.filter(lead_tier=cd["tier"])
        if cd.get("video_status"):
            leads = leads.filter(video_status=cd["video_status"])
        if cd.get("manual_review_status"):
            leads = leads.filter(manual_review_status=cd["manual_review_status"])
        if cd.get("score_min") is not None:
            leads = leads.filter(lead_score__gte=cd["score_min"])
        if cd.get("score_max") is not None:
            leads = leads.filter(lead_score__lte=cd["score_max"])
        if cd.get("has_email"):
            leads = leads.exclude(public_email="")
        if cd.get("has_phone"):
            leads = leads.exclude(public_phone="")
        if cd.get("has_amazon_url"):
            leads = leads.exclude(book__amazon_book_url="")
        if cd.get("has_website"):
            leads = leads.exclude(author_profile__canonical_website="")
        if cd.get("do_not_contact"):
            leads = leads.filter(do_not_contact=True)
        if cd.get("min_confidence"):
            leads = leads.filter(extraction_confidence__gte=float(cd["min_confidence"]))
        if cd.get("pub_year_start") is not None:
            leads = leads.exclude(book__publication_date="").filter(book__publication_date__gte=str(cd["pub_year_start"]))
        if cd.get("pub_year_end") is not None:
            leads = leads.exclude(book__publication_date="").filter(book__publication_date__lt=str(int(cd["pub_year_end"]) + 1))

    # Handle sorting
    order_field = "-created_at"  # Default to Newest First as requested by user
    if form.is_valid() and cd.get("sort_by"):
        order_field = cd["sort_by"]
    leads = leads.order_by(order_field)
    
    # Calculate stats for dashboard header
    stats_total = Lead.objects.count()
    stats_hot = Lead.objects.filter(lead_tier="hot").count()
    stats_pending = Lead.objects.filter(manual_review_status="needs_review").count()
    stats_email = _contactable_queryset(Lead.objects.all()).count()
    
    # Pagination
    try:
        per_page = int(request.GET.get('per_page', 25))
    except ValueError:
        per_page = 25
    if per_page not in [25, 50, 100]:
        per_page = 25
        
    paginator = Paginator(leads, per_page)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        "form": form,
        "page_obj": page_obj,
        "per_page": per_page,
        "leads": leads,
        "stats": {
            "total": stats_total,
            "hot": stats_hot,
            "pending": stats_pending,
            "email": stats_email,
        }
    }
    return render(request, "leadfinder/lead_list.html", context)



def lead_detail(request, pk):
    from collections import Counter

    lead = get_object_or_404(
        Lead.objects.select_related("book", "author_profile", "brief").prefetch_related("evidence", "videos"),
        pk=pk,
    )
    field_evidence = {}
    field_evidence_list = {}
    for evidence in lead.evidence.all():
        field_evidence_list.setdefault(evidence.field_name, []).append(evidence)
    for field, evidences in field_evidence_list.items():
        evidences.sort(key=lambda item: item.confidence, reverse=True)
        field_evidence[field] = evidences[0]
    author = lead.author_profile
    contact_rows_raw = [
        ("Official website", author.canonical_website if author else "", "canonical_website"),
        ("Contact page", author.contact_page_url if author else "", "contact_page_url"),
        ("Public email", lead.public_email, "public_email"),
        ("Public phone", lead.public_phone, "public_phone"),
        ("Location", lead.location, "location"),
        ("Instagram", author.instagram_url if author else "", "instagram_url"),
        ("Facebook", author.facebook_url if author else "", "facebook_url"),
        ("TikTok", author.tiktok_url if author else "", "tiktok_url"),
        ("YouTube", author.youtube_url if author else "", "youtube_url"),
        ("LinkedIn", author.linkedin_url if author else "", "linkedin_url"),
        ("Publisher URL", author.publisher_url if author else "", "publisher_url"),
    ]
    contact_rows = []
    contact_fields = {"public_email", "public_phone", "representation_email", "publicist_email"}
    for label, value, field in contact_rows_raw:
        row_evidences = []
        if value:
            row_evidences = [
                item
                for item in field_evidence_list.get(field, [])
                if str(item.field_value) == str(value) and not is_catalog_or_platform_source(item.source_url)
            ][:3]
        if field in contact_fields:
            is_verified = bool(value and has_verified_contact_source(lead, field, value, min_confidence=0.55 if field == "public_phone" else 0.6))
        else:
            is_verified = bool(
                value
                and row_evidences
                and any(
                    item.confidence >= 0.65
                    and item.evidence_type in {"contact_page", "official_author_site", "publisher_site", "manual", "groq_extraction", "social_profile"}
                    for item in row_evidences
                )
            )
        contact_rows.append(
            {
                "label": label,
                "value": value,
                "evidence": row_evidences[0] if row_evidences else field_evidence.get(field),
                "evidences": row_evidences,
                "is_verified": is_verified,
                "is_url": str(value).startswith("http"),
            }
        )

    # =========================================================================
    # ADVANCED DATA CONSOLIDATION & CONSENSUS AUDITING ENGINE
    # =========================================================================
    author_name = lead.book.author_name.strip() if lead.book.author_name else ""
    sibling_leads = []
    sibling_books = []
    
    if author_name:
        # Cross-reference by name or linked AuthorProfile ID
        q_filter_lead = Q(book__author_name__iexact=author_name)
        if lead.author_profile_id:
            q_filter_lead |= Q(author_profile_id=lead.author_profile_id)
            
        sibling_leads = list(
            Lead.objects.filter(q_filter_lead)
            .select_related("book", "author_profile")
            .prefetch_related("evidence")
            .distinct()
        )
        
        q_filter_book = Q(author_name__iexact=author_name)
        if lead.author_profile_id:
            q_filter_book |= Q(leads__author_profile_id=lead.author_profile_id)
            
        sibling_books = list(
            Book.objects.filter(q_filter_book)
            .select_related("research_run")
            .prefetch_related("leads")
            .distinct()
        )
    else:
        sibling_leads = [lead]
        if lead.book:
            sibling_books = [lead.book]

    # Contact channels to check for cross-lead consistency
    fields_to_check = [
        # (field_key, display_label, is_profile_field)
        ("public_email", "Public Email", False),
        ("public_phone", "Public Phone", False),
        ("location", "Location", False),
        ("representation_email", "Representation Email", False),
        ("publicist_email", "Publicist Email", False),
        ("canonical_website", "Official Website", True),
        ("contact_page_url", "Contact Page", True),
        ("instagram_url", "Instagram", True),
        ("facebook_url", "Facebook", True),
        ("tiktok_url", "TikTok", True),
        ("youtube_url", "YouTube", True),
        ("linkedin_url", "LinkedIn", True),
        ("goodreads_url", "Goodreads", True),
        ("amazon_author_url", "Amazon Author Page", True),
        ("publisher_url", "Publisher URL", True),
    ]

    field_observations = {f_key: [] for f_key, _, _ in fields_to_check}

    for s_lead in sibling_leads:
        ap = s_lead.author_profile
        for f_key, _, is_profile in fields_to_check:
            val = ""
            if is_profile:
                if ap:
                    val = getattr(ap, f_key, "")
            else:
                val = getattr(s_lead, f_key, "")
            
            if val:
                val_clean = str(val).strip()
                # Normalize for casing differences
                if "@" in val_clean or val_clean.startswith("http") or f_key in ["public_email", "representation_email", "publicist_email"]:
                    val_clean_norm = val_clean.lower()
                else:
                    val_clean_norm = val_clean
                
                # Retrieve scraping evidence matching this specific value
                matching_evidences = []
                for ev in s_lead.evidence.all():
                    if ev.field_name == f_key and str(ev.field_value).strip().lower() == val_clean_norm:
                        matching_evidences.append({
                            "source_url": ev.source_url,
                            "evidence_type": ev.evidence_type,
                            "confidence": int(ev.confidence * 100) if ev.confidence else 0
                        })
                
                source_info = {
                    "lead_id": str(s_lead.id),
                    "book_title": s_lead.book.title if s_lead.book else "Unknown Book",
                    "book_asin": s_lead.book.asin if s_lead.book else "",
                    "publisher": s_lead.book.publisher or "Self-published",
                    "publication_date": s_lead.book.publication_date or "—",
                    "source_provider": s_lead.book.source_provider or "Unknown Source",
                    "evidences": matching_evidences
                }
                
                field_observations[f_key].append({
                    "norm": val_clean_norm,
                    "orig": val_clean,
                    "source": source_info
                })

    consensus_contacts = {}
    for f_key, f_label, is_profile in fields_to_check:
        obs = field_observations[f_key]
        
        # Get current value for this specific lead
        current_val = ""
        if is_profile:
            if lead.author_profile:
                current_val = getattr(lead.author_profile, f_key, "")
        else:
            current_val = getattr(lead, f_key, "")
        current_val = str(current_val).strip()
        
        # Normalize current value
        if "@" in current_val or current_val.startswith("http") or f_key in ["public_email", "representation_email", "publicist_email"]:
            current_val_norm = current_val.lower()
        else:
            current_val_norm = current_val

        if not obs:
            consensus_contacts[f_key] = {
                "label": f_label,
                "consensus_value": "",
                "confidence_percentage": 0,
                "total_records": 0,
                "status": "missing",  # missing, consistent, conflict, consistent_with_conflict, available_elsewhere
                "current_value": current_val,
                "alternatives": [],
                "is_url": False,
                "consensus_sources": [],
            }
            continue
            
        # Count frequencies
        norm_counts = Counter([item["norm"] for item in obs])
        total_obs = len(obs)
        
        # Get consensus (most common)
        most_common_norm, count = norm_counts.most_common(1)[0]
        most_common_orig = next(item["orig"] for item in obs if item["norm"] == most_common_norm)
        
        confidence_pct = int((count / total_obs) * 100)
        
        # Classify consistency status
        if not current_val:
            status = "available_elsewhere"
        elif current_val_norm != most_common_norm:
            status = "conflict"
        elif len(norm_counts) > 1:
            status = "consistent_with_conflict"
        else:
            status = "consistent"
            
        # Compile sources matching the consensus value
        consensus_sources = [item["source"] for item in obs if item["norm"] == most_common_norm]
            
        # Alternatives (other than consensus)
        alternatives = []
        for norm_val, cnt in norm_counts.items():
            if norm_val != most_common_norm:
                orig_val = next(item["orig"] for item in obs if item["norm"] == norm_val)
                pct = int((cnt / total_obs) * 100)
                alt_sources = [item["source"] for item in obs if item["norm"] == norm_val]
                alternatives.append({
                    "value": orig_val,
                    "count": cnt,
                    "percentage": pct,
                    "sources": alt_sources
                })
                
        consensus_contacts[f_key] = {
            "label": f_label,
            "consensus_value": most_common_orig,
            "confidence_percentage": confidence_pct,
            "total_records": total_obs,
            "matching_records": count,
            "status": status,
            "current_value": current_val,
            "alternatives": alternatives,
            "is_url": most_common_orig.startswith("http"),
            "consensus_sources": consensus_sources,
        }

    # =========================================================================
    # AUTHOR'S BIBLIOGRAPHY / PUBLISHING FOOTPRINT
    # =========================================================================
    portfolio_books = []
    seen_book_asins = set()
    seen_book_titles = set()
    
    # Compile from sibling leads (guarantees we have outreach results)
    for s_lead in sibling_leads:
        bk = s_lead.book
        if not bk:
            continue
        asin_key = (bk.asin or "").upper()
        title_key = bk.title.strip().lower()
        
        if asin_key and asin_key in seen_book_asins:
            continue
        if not asin_key and title_key in seen_book_titles:
            continue
            
        if asin_key:
            seen_book_asins.add(asin_key)
        seen_book_titles.add(title_key)
        
        portfolio_books.append({
            "title": bk.title,
            "cover_image_url": bk.cover_image_url,
            "asin": bk.asin,
            "publisher": bk.publisher or "Self-published",
            "publication_date": bk.publication_date or "—",
            "rating": bk.rating,
            "review_count": bk.review_count,
            "amazon_book_url": bk.amazon_book_url,
            "source_provider": bk.source_provider,
            "marketplace": bk.research_run.marketplace,
            "run_keyword": bk.research_run.keyword or bk.research_run.source_provider,
            "lead_id": s_lead.id,
            "lead_tier": s_lead.lead_tier,
            "manual_review_status": s_lead.manual_review_status,
            "lead_score": s_lead.lead_score,
            "has_lead": True,
            # Sourced contacts specifically for this book
            "email": s_lead.public_email.strip() if s_lead.public_email else "",
            "phone": s_lead.public_phone.strip() if s_lead.public_phone else "",
            "representation_email": s_lead.representation_email.strip() if s_lead.representation_email else "",
            "publicist_email": s_lead.publicist_email.strip() if s_lead.publicist_email else "",
            "location": s_lead.location.strip() if s_lead.location else "",
            "website": s_lead.author_profile.canonical_website.strip() if (s_lead.author_profile and s_lead.author_profile.canonical_website) else "",
        })
        
    # Compile from direct Books (grabs non-lead or incomplete search results)
    for bk in sibling_books:
        asin_key = (bk.asin or "").upper()
        title_key = bk.title.strip().lower()
        
        if asin_key and asin_key in seen_book_asins:
            continue
        if not asin_key and title_key in seen_book_titles:
            continue
            
        if asin_key:
            seen_book_asins.add(asin_key)
        seen_book_titles.add(title_key)
        
        ld = bk.leads.first()
        
        portfolio_books.append({
            "title": bk.title,
            "cover_image_url": bk.cover_image_url,
            "asin": bk.asin,
            "publisher": bk.publisher or "Self-published",
            "publication_date": bk.publication_date or "—",
            "rating": bk.rating,
            "review_count": bk.review_count,
            "amazon_book_url": bk.amazon_book_url,
            "source_provider": bk.source_provider,
            "marketplace": bk.research_run.marketplace,
            "run_keyword": bk.research_run.keyword or bk.research_run.source_provider,
            "lead_id": ld.id if ld else None,
            "lead_tier": ld.lead_tier if ld else "—",
            "manual_review_status": ld.manual_review_status if ld else "—",
            "lead_score": ld.lead_score if ld else 0,
            "has_lead": ld is not None,
            # Sourced contacts specifically for this book
            "email": ld.public_email.strip() if (ld and ld.public_email) else "",
            "phone": ld.public_phone.strip() if (ld and ld.public_phone) else "",
            "representation_email": ld.representation_email.strip() if (ld and ld.representation_email) else "",
            "publicist_email": ld.publicist_email.strip() if (ld and ld.publicist_email) else "",
            "location": ld.location.strip() if (ld and ld.location) else "",
            "website": ld.author_profile.canonical_website.strip() if (ld and ld.author_profile and ld.author_profile.canonical_website) else "",
        })

    return render(
        request,
        "leadfinder/lead_detail.html",
        {
            "lead": lead,
            "field_evidence": field_evidence,
            "contact_rows": contact_rows,
            "consensus_contacts": consensus_contacts,
            "portfolio_books": portfolio_books,
            "sibling_leads_count": len(sibling_leads),
        },
    )


@require_POST
def run_stop(request, pk):
    run = get_object_or_404(ResearchRun, pk=pk)
    if run.status in {"pending", "running"}:
        run.mark_canceled()
        messages.success(request, "Stop requested. The runner will exit at the next safe checkpoint.")
    else:
        messages.info(request, f"Run is already {run.status}.")
    
    redirect_url = request.POST.get("next") or request.GET.get("next") or request.META.get("HTTP_REFERER")
    if redirect_url:
        return redirect(redirect_url)
    return redirect("leadfinder:run_detail", pk=run.id)


@require_POST
def run_retry(request, pk):
    old_run = get_object_or_404(ResearchRun, pk=pk)
    new_settings = dict(old_run.settings_json or {})
    if old_run.source_provider == "ddgs":
        new_settings.setdefault("google_books_fallback", True)
    run = ResearchRun.objects.create(
        keyword=old_run.keyword,
        source_provider=old_run.source_provider,
        marketplace=old_run.marketplace,
        max_books=old_run.max_books,
        settings_json=new_settings,
    )
    _start_research_pipeline(run.id)
    messages.success(request, "Retry started as a new research run.")
    return redirect("leadfinder:run_detail", pk=run.id)


@require_POST
def lead_action(request, pk, action):
    lead = get_object_or_404(Lead, pk=pk)
    if action == "delete":
        lead.delete()
        messages.success(request, "Lead deleted successfully.")
        return redirect("leadfinder:lead_list")
    elif action == "approve":
        ok, errors = can_approve_lead(lead, manual_identity_override=True)
        if ok:
            lead.manual_review_status = "approved"
            messages.success(request, "Lead approved.")
        else:
            messages.error(request, "Cannot approve: " + "; ".join(errors))
    elif action == "reject":
        lead.manual_review_status = "rejected"
        messages.success(request, "Lead rejected.")
    elif action == "do-not-contact":
        lead.manual_review_status = "do_not_contact"
        lead.do_not_contact = True
        messages.success(request, "Lead marked do-not-contact.")
    elif action == "add-note":
        if not request.POST.get("note", "").strip():
            messages.warning(request, "Enter a note before saving the activity log.")
            return redirect("leadfinder:lead_detail", pk=lead.id)
        messages.success(request, "Activity note saved without changing review status.")
    else:
        messages.error(request, "Unknown lead action.")
        return redirect("leadfinder:lead_detail", pk=lead.id)
    note = request.POST.get("note", "").strip()
    if note:
        lead.notes = f"{lead.notes}\n{note}".strip()
    lead.save()
    return redirect("leadfinder:lead_detail", pk=lead.id)


@require_POST
def lead_bulk_action(request):
    lead_ids = request.POST.getlist("lead_ids")
    action = request.POST.get("action")
    redirect_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "leadfinder:lead_list"
    
    if not lead_ids:
        messages.warning(request, "No leads were selected.")
        return redirect(redirect_url)
        
    if action == "bulk_reject":
        updated = Lead.objects.filter(id__in=lead_ids).update(manual_review_status="rejected")
        messages.success(request, f"Successfully rejected {updated} leads.")
    elif action == "bulk_delete":
        deleted_count, _ = Lead.objects.filter(id__in=lead_ids).delete()
        messages.success(request, f"Successfully deleted {deleted_count} leads.")
    else:
        messages.error(request, "Invalid bulk action requested.")
        
    return redirect(redirect_url)


def export_leads_csv(request):
    leads = Lead.objects.exclude(lead_tier="rejected").exclude(
        Q(manual_review_status__in=["rejected", "do_not_contact"]) | Q(do_not_contact=True)
    ).order_by("-lead_score", "-created_at")
    valid_only = request.GET.get("valid_only", "0").lower() not in {"0", "false", "all", "no", ""}
    if valid_only:
        leads = _contactable_queryset(leads.exclude(lead_tier__in=["cold", "rejected"]).exclude(book__amazon_book_url=""))
    limit = request.GET.get("limit")
    if limit:
        try:
            leads = leads[: max(1, min(int(limit), 700))]
        except ValueError:
            pass
    return export_leads_response(leads)


def export_leads_xlsx_view(request):
    leads = Lead.objects.exclude(lead_tier="rejected").exclude(
        Q(manual_review_status__in=["rejected", "do_not_contact"]) | Q(do_not_contact=True)
    ).order_by("-lead_score", "-created_at")
    valid_only = request.GET.get("valid_only", "0").lower() not in {"0", "false", "all", "no", ""}
    if valid_only:
        leads = _contactable_queryset(leads.exclude(lead_tier__in=["cold", "rejected"]).exclude(book__amazon_book_url=""))
    limit = request.GET.get("limit")
    if limit:
        try:
            leads = leads[: max(1, min(int(limit), 700))]
        except ValueError:
            pass
    return export_leads_xlsx(leads)


def settings_help(request):
    def configured(name: str) -> bool:
        return bool(os.getenv(name))

    def installed(module_name: str) -> bool:
        return importlib.util.find_spec(module_name) is not None

    booklife_direct_fetch = os.getenv("BOOKLIFE_DIRECT_FETCH_ALLOWED", "").lower() in {"1", "true", "yes", "on"}

    context = {
        "search_provider": os.getenv("SEARCH_PROVIDER", "ddgs"),
        "keys": {
            "GOOGLE_API_KEY": configured("GOOGLE_API_KEY"),
            "GOOGLE_CSE_ID": configured("GOOGLE_CSE_ID"),
            "TAVILY_API_KEY": configured("TAVILY_API_KEY"),
            "BRAVE_API_KEY": configured("BRAVE_API_KEY"),
            "GROQ_API_KEY": configured("GROQ_API_KEY"),
            "YOUTUBE_API_KEY": configured("YOUTUBE_API_KEY"),
            "GOOGLE_BOOKS_API_KEY": configured("GOOGLE_BOOKS_API_KEY"),
            "AMAZON_CREATORS_CLIENT_ID": configured("AMAZON_CREATORS_CLIENT_ID"),
            "AMAZON_CREATORS_CLIENT_SECRET": configured("AMAZON_CREATORS_CLIENT_SECRET"),
        },
        "scraping_tools": [
            {
                "name": "DDGS",
                "purpose": "Default no-key public web search fallback.",
                "status": "Available" if installed("ddgs") else "Missing package",
            },
            {
                "name": "Google Custom Search",
                "purpose": "Optional Google search provider for premium discovery results.",
                "status": "Configured" if (configured("GOOGLE_API_KEY") and configured("GOOGLE_CSE_ID")) else "Missing API key/CSE ID",
            },
            {
                "name": "Tavily",
                "purpose": "Optional API-backed web search provider.",
                "status": "Configured" if configured("TAVILY_API_KEY") else "Missing API key",
            },
            {
                "name": "Brave Search",
                "purpose": "Optional API-backed web search provider.",
                "status": "Configured" if configured("BRAVE_API_KEY") else "Missing API key",
            },
            {
                "name": "Google Books",
                "purpose": "Structured book metadata provider for cleaner title, author, ISBN, publisher, category, rating, and cover data.",
                "status": "API key configured" if configured("GOOGLE_BOOKS_API_KEY") else "No-key public mode",
            },
            {
                "name": "ISBN intelligence",
                "purpose": "Checksum agreement, ISBN-10/13 conversion, exact-source reconciliation, and SVG barcode output.",
                "status": "Available" if all(installed(name) for name in ("isbnlib", "pyisbn", "barcode")) else "Missing package",
            },
            {
                "name": "BookLife",
                "purpose": "Category-based project discovery that feeds author/contact enrichment.",
                "status": "Direct fetch enabled" if booklife_direct_fetch else "Robots-respecting mode",
            },
            {
                "name": "Scrapy",
                "purpose": "Batch author-site scraping commands.",
                "status": "Available" if installed("scrapy") else "Missing package",
            },
            {
                "name": "Groq",
                "purpose": "Optional structured AI extraction and briefs.",
                "status": "Configured" if configured("GROQ_API_KEY") else "Fallback mode",
            },
        ],
        "local_checks": [
            {
                "label": "Run app tests",
                "command": r"..\.venv\Scripts\python.exe -m pytest",
            },
            {
                "label": "Run Django checks",
                "command": r"..\.venv\Scripts\python.exe manage.py check",
            },
            {
                "label": "One-command local verification",
                "command": r".\scripts\test_leadfinder.ps1",
            },
        ],
    }
    return render(request, "leadfinder/settings_help.html", context)


def isbn_search(request):
    run_id = request.GET.get("run_id")
    active_run = None
    if run_id:
        try:
            active_run = ResearchRun.objects.get(id=run_id)
        except (ResearchRun.DoesNotExist, ValueError):
            pass

    if request.method == "POST":
        form = ISBNSearchForm(request.POST)
        if form.is_valid():
            identifier_analyses = form.identifier_analyses
            isbn_list = [item.canonical for item in identifier_analyses]

            if not isbn_list:
                messages.error(request, "Please enter at least one valid ASIN or ISBN.")
                return redirect("leadfinder:isbn_search")

            run_video = form.cleaned_data["run_video_search"]
            run_ai = form.cleaned_data["run_groq_ai_extraction"]

            # Try to see if this book already exists in DB with valid author
            if len(isbn_list) == 1:
                analysis = identifier_analyses[0]
                aliases = [value for value in {analysis.canonical, analysis.isbn10, analysis.isbn13} if value]
                book = Book.objects.filter(asin__in=aliases).exclude(author_name="").order_by("-book_data_confidence").first()
                if (
                    book
                    and analysis.identifier_type in {"isbn10", "isbn13"}
                    and not (book.source_raw_json or {}).get("metadata_resolution")
                ):
                    book = None
                if book:
                    lead = Lead.objects.filter(book=book).select_related("book", "author_profile").first()
                    if lead:
                        messages.info(request, f"Book details and lead for {analysis.display} retrieved from the evidence cache.")
                        return redirect("leadfinder:lead_detail", pk=lead.id)

            # Keyword description:
            if len(isbn_list) == 1:
                keyword_text = f"ISBN Search: {isbn_list[0]}"
            else:
                keyword_text = f"Batch ISBN Search ({len(isbn_list)} items)"

            # Create a Manual/ISBN ResearchRun
            run = ResearchRun.objects.create(
                keyword=keyword_text,
                source_provider="manual",
                max_books=len(isbn_list),
                settings_json={
                    "require_amazon_url": False,
                    "require_public_email": False,
                    "include_social_only_leads": True,
                    "run_video_search": run_video,
                    "run_groq_ai_extraction": run_ai,
                }
            )

            # Create initial Book records
            for analysis in identifier_analyses:
                code = analysis.canonical
                is_asin = analysis.identifier_type == "asin"
                supplied_amazon_url = normalize_amazon_book_url(analysis.raw) if is_asin and is_amazon_url(analysis.raw) else ""
                Book.objects.create(
                    research_run=run,
                    title=f"Book for {analysis.identifier_type.upper()} {code}",
                    asin=code,
                    amazon_book_url=supplied_amazon_url,
                    amazon_source_url=supplied_amazon_url,
                    normalized_key=normalized_book_key(f"Book for {analysis.identifier_type.upper()} {code}", "", code),
                    book_data_confidence=analysis.confidence,
                    source_provider="manual",
                    source_raw_json={
                        "processing_status": "pending",
                        "identifier_intelligence": analysis.as_dict(),
                    },
                )

            # Start background pipeline
            _start_research_pipeline(run.id)

            return redirect(f"{reverse('leadfinder:isbn_search')}?run_id={run.id}")
    else:
        form = ISBNSearchForm()

    return render(request, "leadfinder/isbn_search.html", {
        "form": form,
        "active_run": active_run,
        "isbn_stack": ["isbnlib", "pyisbn", "Google Books", "Open Library", "Library of Congress", "python-barcode"],
    })


@require_GET
def isbn_analyze(request):
    analysis = analyze_identifier(request.GET.get("identifier", ""))
    payload = analysis.as_dict()
    if analysis.barcode_available:
        payload["barcode_url"] = reverse("leadfinder:isbn_barcode", kwargs={"identifier": analysis.canonical})
    return JsonResponse(payload, status=200 if analysis.valid else 422)


@require_GET
def isbn_barcode(request, identifier):
    try:
        svg = generate_barcode_svg(identifier)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=422)
    response = HttpResponse(svg, content_type="image/svg+xml")
    response["Content-Disposition"] = f'inline; filename="isbn-{analyze_identifier(identifier).isbn13}.svg"'
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def isbn_search_status(request, run_id):
    run = get_object_or_404(ResearchRun, id=run_id)
    books = run.books.all().order_by("created_at")

    total_books = books.count()
    completed_books = 0
    failed_books = 0
    pending_books = 0
    processing_books = 0

    tasks_list = []

    for book in books:
        raw = book.source_raw_json or {}
        status = raw.get("processing_status", "pending")

        # Fallback check: if book has processing status as pending/processing but the run itself is finished/failed/canceled,
        # show it as failed or skipped to avoid endless loading UI if the runner crashed.
        if status in ("pending", "processing") and run.status in ("completed", "failed", "canceled"):
            status = "failed"

        if status == "completed":
            completed_books += 1
        elif status == "failed":
            failed_books += 1
        elif status == "processing":
            processing_books += 1
        else:
            pending_books += 1

        # Find lead ID if completed
        lead_id = None
        if status == "completed":
            lead = book.leads.first()
            if lead:
                lead_id = str(lead.id)

        errors = raw.get("book_processing_errors", [])

        tasks_list.append({
            "asin": book.asin,
            "title": book.title,
            "author": book.author_name or "Searching...",
            "status": status,
            "lead_id": lead_id,
            "errors": errors,
            "identifier": raw.get("identifier_intelligence", {}),
        })

    # Calculate percentage
    finished_count = completed_books + failed_books
    if total_books > 0:
        percentage = int((finished_count / total_books) * 100)
    else:
        percentage = 0

    # Calculate ETC
    etc_str = "Estimating..."
    if run.status == "completed":
        etc_str = "Complete"
    elif run.status in ("failed", "canceled"):
        etc_str = run.status.capitalize()
    else:
        # Active run
        from django.utils import timezone
        started_at = run.started_at or run.created_at
        elapsed = (timezone.now() - started_at).total_seconds()
        if elapsed <= 0:
            elapsed = 1.0
        if finished_count > 0:
            seconds_per_book = elapsed / finished_count
            remaining_books = total_books - finished_count
            remaining_seconds = remaining_books * seconds_per_book
            if remaining_seconds < 60:
                etc_str = f"{int(remaining_seconds)}s remaining"
            else:
                minutes = int(remaining_seconds // 60)
                seconds = int(remaining_seconds % 60)
                etc_str = f"{minutes}m {seconds}s remaining"
        else:
            etc_str = "Estimating..."

    return JsonResponse({
        "run_id": str(run.id),
        "status": run.status,
        "total": total_books,
        "completed": completed_books,
        "processing": processing_books,
        "pending": pending_books,
        "failed": failed_books,
        "percentage": percentage,
        "etc": etc_str,
        "tasks": tasks_list,
    })


def _legacy_isbn_lookup_tavily_stream(request):
    keyword = request.GET.get("keyword", "").strip()
    pub_year_start = request.GET.get("pub_year_start", "").strip()
    pub_year_end = request.GET.get("pub_year_end", "").strip()
    try:
        max_results = int(request.GET.get("max_results", "50"))
        max_results = max(1, min(max_results, 1000))
    except ValueError:
        max_results = 50
    if not keyword:
        return JsonResponse({"error": "Keyword is required."}, status=400)

    import logging
    logger = logging.getLogger(__name__)

    def event_stream():
        import json
        import re
        import time
        from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
        from leadfinder.services.pipeline.run_research import guess_title_author

        yield json.dumps({"status": "starting", "message": "Initiating deep search..."}) + "\n"

        books_yielded = 0
        seen_ids: set = set()

        # Parse year filters
        start: int | None = None
        end: int | None = None
        if pub_year_start:
            try:
                start = int(pub_year_start)
            except ValueError:
                pass
        if pub_year_end:
            try:
                end = int(pub_year_end)
            except ValueError:
                pass

        def year_ok(year_val) -> bool:
            if year_val is None or year_val == "":
                return True
            try:
                y = int(year_val)
            except (TypeError, ValueError):
                return True
            if start and y < start:
                return False
            if end and y > end:
                return False
            return True

        def emit_book(book: dict) -> str:
            """Yield a single book as a progress event."""
            nonlocal books_yielded
            books_yielded += 1
            return json.dumps({
                "status": "progress",
                "books": [book],
                "count": books_yielded,
            }) + "\n"

        def process_search_results(results, source_name: str):
            """Extract books from search results and yield them one by one."""
            for dto in results:
                if books_yielded >= max_results:
                    return
                asin = extract_asin(dto.url)
                if not (is_amazon_url(dto.url) and asin):
                    continue
                if asin in seen_ids:
                    continue
                year_match = re.search(
                    r"\b(19\d{2}|20\d{2})\b",
                    f"{dto.title} {dto.snippet or ''}"
                )
                pub_year = year_match.group(0) if year_match else ""
                if not year_ok(pub_year if pub_year else None):
                    continue
                seen_ids.add(asin)
                title, author, _ = guess_title_author(dto.title, dto.snippet or "")

                # Enrich author/cover/date via Google Books & Open Library if missing
                cover_image_url = ""
                final_pub_date = pub_year
                if not author:
                    try:
                        from leadfinder.services.amazon.amazon_scraper import fetch_metadata_from_free_apis
                        api_data = fetch_metadata_from_free_apis(asin)
                        if api_data:
                            api_authors = api_data.get("authors", [])
                            if api_authors:
                                first = api_authors[0]
                                author = first.get("name", "") if isinstance(first, dict) else str(first)
                            if not pub_year and api_data.get("publication_date"):
                                raw_date = str(api_data["publication_date"])
                                y_match = re.search(r"\b(19\d{2}|20\d{2})\b", raw_date)
                                if y_match:
                                    final_pub_date = y_match.group(0)
                            if api_data.get("cover_image_url"):
                                cover_image_url = api_data["cover_image_url"]
                            if not title and api_data.get("title"):
                                title = api_data["title"]
                    except Exception as enrich_err:
                        logger.debug("Author enrichment via API failed for %s: %s", asin, enrich_err)

                yield emit_book({
                    "title": title or dto.title,
                    "author_name": author,
                    "asin": asin,
                    "publication_date": final_pub_date,
                    "cover_image_url": cover_image_url,
                    "source": source_name,
                })

        # Build year-specific query variants
        years = []
        if start and end:
            years = list(range(start, end + 1))
        elif start:
            years = [start]
        elif end:
            years = [end]

        year_str = " ".join(str(y) for y in years) if years else ""

        # ── Build diverse queries (plain text — no site:, no quotes) ───────────
        queries: list[str] = []

        if years:
            for y in years:
                queries += [
                    f"amazon {keyword} {y}",
                    f"{keyword} amazon {y} book",
                    f"amazon {keyword} {y} paperback",
                    f"amazon {keyword} {y} picture book",
                    f"amazon {keyword} {y} new release",
                    f"{keyword} {y} buy amazon",
                    f"amazon {keyword} {y} hardcover",
                    f"amazon {keyword} {y} children",
                    f"{keyword} {y} ISBN book",
                    f"amazon {keyword} {y} illustrated",
                    f"{keyword} {y} book author amazon",
                    f"amazon new books {keyword} {y}",
                    f"{keyword} {y} book isbn amazon bestseller",
                    f"amazon {keyword} {y} ages kids",
                    f"{keyword} published {y} amazon",
                ]
        else:
            queries += [
                f"amazon {keyword} book",
                f"{keyword} amazon paperback",
                f"{keyword} amazon children book",
                f"amazon {keyword} picture book",
                f"{keyword} amazon new release",
                f"amazon {keyword} illustrated",
                f"{keyword} amazon hardcover",
                f"{keyword} book ISBN",
            ]

        # Add broad year-range queries
        if year_str:
            queries += [
                f"amazon {keyword} {year_str}",
                f"{keyword} {year_str} amazon books",
                f"new {keyword} {year_str} amazon",
                f"best {keyword} {year_str} amazon",
                f"{keyword} award {year_str} amazon",
            ]

        # Deduplicate
        seen_q: set = set()
        unique_queries = []
        for q in queries:
            if q not in seen_q:
                seen_q.add(q)
                unique_queries.append(q)

        # ── SOURCE: Tavily search (confirmed working) ───────────────────────────
        try:
            from leadfinder.services.search.tavily_provider import TavilySearchProvider
            tavily = TavilySearchProvider()

            for i, query in enumerate(unique_queries):
                if books_yielded >= max_results:
                    break

                yield json.dumps({
                    "status": "searching",
                    "message": f"[{i+1}/{len(unique_queries)}] Scanning: {query}",
                    "count": books_yielded,
                }) + "\n"

                try:
                    results = tavily.search(query, max_results=10)
                    for event in process_search_results(results, "tavily"):
                        yield event
                        if books_yielded >= max_results:
                            break
                except Exception as ex:
                    logger.warning("Tavily query '%s' failed: %s", query, ex)

                time.sleep(0.2)

        except Exception as e:
            logger.error("Tavily search block failed: %s", e)

        # ── FALLBACK: DDG HTML (if Tavily found nothing) ────────────────────────
        if books_yielded == 0:
            try:
                from leadfinder.services.search.ddgs_html_provider import DDGHTMLSearchProvider
                ddg = DDGHTMLSearchProvider(delay=0.5)
                fallback_queries = unique_queries[:5]  # Try first 5 only
                for query in fallback_queries:
                    if books_yielded >= max_results:
                        break
                    yield json.dumps({
                        "status": "searching",
                        "message": f"Fallback search: {query}",
                        "count": books_yielded,
                    }) + "\n"
                    try:
                        results = ddg.search(query, max_results=15)
                        for event in process_search_results(results, "ddg"):
                            yield event
                    except Exception as ex:
                        logger.warning("DDG fallback query '%s' failed: %s", query, ex)
                    time.sleep(0.5)
            except Exception as e:
                logger.warning("DDG fallback failed: %s", e)

        yield json.dumps({"status": "done", "count": books_yielded}) + "\n"

    from django.http import StreamingHttpResponse
    response = StreamingHttpResponse(event_stream(), content_type="application/x-ndjson")
    response["X-Accel-Buffering"] = "no"
    response["Cache-Control"] = "no-cache"
    return response


def isbn_lookup(request):
    keyword = request.GET.get("keyword", "").strip()
    pub_year_start = request.GET.get("pub_year_start", "").strip()
    pub_year_end = request.GET.get("pub_year_end", "").strip()
    only_new = request.GET.get("only_new", "false").lower() == "true"
    try:
        max_results = int(request.GET.get("max_results", "50"))
        max_results = max(1, min(max_results, 1000))
    except ValueError:
        max_results = 50
    if not keyword:
        return JsonResponse({"error": "Keyword is required."}, status=400)

    def event_stream():
        import json

        from leadfinder.services.books.isbn_keyword_lookup import stream_keyword_lookup

        for event in stream_keyword_lookup(keyword, pub_year_start, pub_year_end, max_results, only_new=only_new):
            yield json.dumps(event, ensure_ascii=True) + "\n"

    from django.http import StreamingHttpResponse

    response = StreamingHttpResponse(event_stream(), content_type="application/x-ndjson")
    response["X-Accel-Buffering"] = "no"
    response["Cache-Control"] = "no-cache"
    return response


    keyword = request.GET.get("keyword", "").strip()
    pub_year_start = request.GET.get("pub_year_start", "").strip()
    pub_year_end = request.GET.get("pub_year_end", "").strip()
    try:
        max_results = int(request.GET.get("max_results", "50"))
        max_results = max(1, min(max_results, 1000))
    except ValueError:
        max_results = 50
    if not keyword:
        return JsonResponse({"error": "Keyword is required."}, status=400)

    import logging
    logger = logging.getLogger(__name__)

    def event_stream():
        import json
        import re
        import time
        from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
        from leadfinder.services.pipeline.run_research import guess_title_author

        yield json.dumps({"status": "starting", "message": "Initiating search..."}) + "\n"

        books_yielded = 0
        seen_ids: set = set()   # tracks isbn/asin to avoid duplicates

        # Parse year filters
        start: int | None = None
        end: int | None = None
        if pub_year_start:
            try:
                start = int(pub_year_start)
            except ValueError:
                pass
        if pub_year_end:
            try:
                end = int(pub_year_end)
            except ValueError:
                pass

        def year_ok(year_val) -> bool:
            """True if the year is within the requested range (None = unknown → pass through)."""
            if year_val is None:
                return True   # unknown year — allow
            try:
                y = int(year_val)
            except (TypeError, ValueError):
                return True
            if start and y < start:
                return False
            if end and y > end:
                return False
            return True

        # ── SOURCE 1: Open Library (most reliable, direct ISBNs) ──────────────
        yield json.dumps({"status": "searching",
                          "message": "Searching Open Library for ISBNs...",
                          "count": books_yielded}) + "\n"
        try:
            from leadfinder.services.books.open_library_provider import search_openlibrary
            ol_books = search_openlibrary(
                keyword=keyword,
                year_start=start,
                year_end=end,
                max_books=min(max_results, 200),
            )
            ol_batch = []
            for b in ol_books:
                bid = b.get("isbn") or b.get("asin") or ""
                if bid and bid not in seen_ids:
                    seen_ids.add(bid)
                    ol_batch.append(b)
                    books_yielded += 1
                    if books_yielded >= max_results:
                        break
            if ol_batch:
                yield json.dumps({
                    "status": "progress",
                    "books": ol_batch,
                    "count": books_yielded
                }) + "\n"
        except Exception as e:
            logger.warning("Open Library search failed: %s", e)

        # ── SOURCE 2: DDG HTML scraping of Amazon URLs ─────────────────────────
        if books_yielded < max_results:
            try:
                from leadfinder.services.search.ddgs_html_provider import DDGHTMLSearchProvider
                ddg = DDGHTMLSearchProvider(delay=0.4)

                years = []
                if start and end:
                    years = list(range(start, end + 1))
                elif start:
                    years = [start]
                elif end:
                    years = [end]

                # Build targeted queries
                queries: list[str] = []

                for y in years:
                    queries += [
                        f"site:amazon.com {keyword} {y}",
                        f"amazon {keyword} {y} paperback",
                        f"amazon {keyword} {y} hardcover",
                        f"amazon.com {keyword} {y} children book",
                        f"amazon {keyword} {y} picture book",
                        f"site:amazon.com {keyword} {y} illustrated",
                        f"buy {keyword} {y} amazon",
                        f"{keyword} {y} ISBN amazon",
                        f"amazon {keyword} {y} new book",
                        f"site:amazon.com {keyword} {y} kids",
                    ]

                # Broad queries (no year)
                queries += [
                    f"site:amazon.com {keyword} paperback",
                    f"amazon.com {keyword} book",
                    f"site:amazon.com {keyword} children",
                    f"{keyword} amazon books ISBN",
                    f"amazon {keyword} picture book",
                ]

                # De-duplicate queries
                seen_q: set = set()
                unique_q = []
                for q in queries:
                    if q not in seen_q:
                        seen_q.add(q)
                        unique_q.append(q)

                for query in unique_q:
                    if books_yielded >= max_results:
                        break

                    yield json.dumps({
                        "status": "searching",
                        "message": f"Searching: {query}...",
                        "count": books_yielded
                    }) + "\n"

                    try:
                        results = ddg.search(query, max_results=20)
                        new_books = []
                        for dto in results:
                            if books_yielded >= max_results:
                                break
                            asin = extract_asin(dto.url)
                            if not (is_amazon_url(dto.url) and asin):
                                continue
                            if asin in seen_ids:
                                continue

                            # Extract pub year from title/snippet
                            year_match = re.search(
                                r"\b(19\d{2}|20\d{2})\b",
                                f"{dto.title} {dto.snippet or ''}"
                            )
                            pub_year = year_match.group(0) if year_match else ""

                            if not year_ok(pub_year if pub_year else None):
                                continue

                            seen_ids.add(asin)
                            title, author, _ = guess_title_author(dto.title, dto.snippet or "")
                            new_books.append({
                                "title": title,
                                "author_name": author,
                                "asin": asin,
                                "publication_date": pub_year,
                                "cover_image_url": "",
                                "source": "ddg_html",
                            })
                            books_yielded += 1

                        if new_books:
                            yield json.dumps({
                                "status": "progress",
                                "books": new_books,
                                "count": books_yielded
                            }) + "\n"

                    except Exception as ex:
                        logger.warning("DDG HTML query '%s' failed: %s", query, ex)
                    time.sleep(0.3)

            except Exception as e:
                logger.error("DDG HTML search block failed: %s", e)

        yield json.dumps({"status": "done", "count": books_yielded}) + "\n"

    from django.http import StreamingHttpResponse
    response = StreamingHttpResponse(event_stream(), content_type="application/x-ndjson")
    response["X-Accel-Buffering"] = "no"
    response["Cache-Control"] = "no-cache"
    return response
