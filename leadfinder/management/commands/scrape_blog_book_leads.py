from __future__ import annotations

import os
import time
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand

from leadfinder.models import Book, Lead, ResearchRun
from leadfinder.services.ai.blog_parser import parse_blog_review
from leadfinder.services.amazon.amazon_url_parser import extract_asin, normalize_amazon_book_url
from leadfinder.services.pipeline.process_book import process_book
from leadfinder.services.search import get_search_provider
from leadfinder.services.export.csv_export import export_leads_to_file
from leadfinder.utils.normalize import normalized_book_key


BLOG_SOURCES = [
    {
        "name": "The Children's Book Review",
        "domain": "thechildrensbookreview.com",
        "query": 'site:thechildrensbookreview.com "picture book" "by"'
    },
    {
        "name": "From the Mixed-Up Files",
        "domain": "fromthemixedupfiles.com",
        "query": 'site:fromthemixedupfiles.com "by" "picture book"'
    },
    {
        "name": "A Fuse 8 Production",
        "domain": "blogs.slj.com/afuse8production",
        "query": 'site:blogs.slj.com/afuse8production "review" "by"'
    },
    {
        "name": "Seven Impossible Things",
        "domain": "blaine.org/sevenimpossiblethings",
        "query": 'site:blaine.org/sevenimpossiblethings "picture book"'
    },
    {
        "name": "KidLit411",
        "domain": "kidlit411.com",
        "query": 'site:kidlit411.com "author spotlight" "by"'
    },
    {
        "name": "Picture Book Builders",
        "domain": "picturebookbuilders.com",
        "query": 'site:picturebookbuilders.com "review" "by"'
    },
    {
        "name": "Book Craic",
        "domain": "bookcraic.blog",
        "query": 'site:bookcraic.blog "review" "picture book"'
    },
    {
        "name": "Read It Daddy",
        "domain": "readitdaddy.blogspot.com",
        "query": 'site:readitdaddy.blogspot.com "picture book"'
    },
    {
        "name": "LitPick",
        "domain": "litpick.com",
        "query": 'site:litpick.com "review" "picture book"'
    },
    {
        "name": "What Do We Do All Day",
        "domain": "whatdowedoallday.com",
        "query": 'site:whatdowedoallday.com "books" "review"'
    }
]


def find_amazon_match(provider, title: str, author: str) -> tuple[str, str] | None:
    """
    Search Amazon via SearchProvider for a given book title and author to extract ASIN and normal URL.
    """
    # Try high-precision query first
    query = f'site:amazon.com "{title}" "{author}"'
    try:
        results = provider.search(query, max_results=5)
    except Exception:
        results = []

    for res in results:
        asin = extract_asin(res.url)
        if asin:
            return normalize_amazon_book_url(res.url), asin

    # Try fallback query with title only
    query_fallback = f'site:amazon.com "{title}"'
    try:
        results = provider.search(query_fallback, max_results=5)
    except Exception:
        results = []

    for res in results:
        asin = extract_asin(res.url)
        if asin:
            return normalize_amazon_book_url(res.url), asin

    return None


class Command(BaseCommand):
    help = "Harvest high-converting children's book author leads from top KidLit blogs on Google."

    def add_arguments(self, parser):
        parser.add_argument("--target-leads", type=int, default=10, help="Target count of qualified leads to harvest.")
        parser.add_argument("--provider", default="tavily", choices=["ddgs", "tavily", "brave"], help="Search provider to use.")
        parser.add_argument("--output", default="data/best_blog_reviewed_leads.csv", help="CSV output destination path.")
        parser.add_argument("--no-video-search", action="store_true", help="Skip YouTube book trailer classification search.")
        parser.add_argument("--no-ai", action="store_true", help="Disable AI extraction prompts and fall back to regex/heuristics.")

    def _output_path(self, output_option: str) -> Path:
        output = Path(output_option)
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)
        return output

    def handle(self, *args, **options):
        target = max(1, min(options["target_leads"], 50))
        provider = get_search_provider(options["provider"])
        output_file = self._output_path(options["output"])
        
        self.stdout.write(self.style.NOTICE("=================================================================="))
        self.stdout.write(self.style.SUCCESS("[>>>] KIDLIT BLOG REVIEWS LEAD HARVESTER - INITIALIZING NEXT-LEVEL ENGINE"))
        self.stdout.write(self.style.NOTICE(f"[TARGET] Target: {target} qualified leads | Provider: {options['provider'].upper()}"))
        self.stdout.write(self.style.NOTICE("=================================================================="))
        
        # Create a single parent ResearchRun for tracking
        run = ResearchRun.objects.create(
            keyword="KidLit Blog Reviews Harvester",
            source_provider=options["provider"],
            max_books=target * 3,
            settings_json={
                "run_video_search": not options["no_video_search"],
                "run_groq_ai_extraction": not options["no_ai"],
                "target_leads": target
            }
        )
        
        leads_processed: list[Lead] = []
        seen_asins: set[str] = set()
        
        # Loop over our configured children's book blogs
        for source in BLOG_SOURCES:
            if len(leads_processed) >= target:
                break
                
            self.stdout.write(self.style.NOTICE(f"\n[SEARCH] Searching Blog Source: {source['name']} ({source['domain']})..."))
            
            try:
                results = provider.search(source["query"], max_results=target * 2)
            except Exception as exc:
                self.stderr.write(f"[WARNING] Search failed for query '{source['query']}': {exc}")
                continue
                
            self.stdout.write(f"Found {len(results)} potential review entries. Parsing for book & author details...")
            
            for res in results:
                if len(leads_processed) >= target:
                    break
                    
                # Skip pages that aren't reviews or aren't on the domain
                if source["domain"] not in res.url.lower():
                    continue
                    
                parsed = parse_blog_review(res.title, res.snippet, use_ai=not options["no_ai"])
                if not parsed.book_title or not parsed.author_name:
                    continue
                    
                self.stdout.write(f"  [BOOK] Discovered review: '{parsed.book_title}' by {parsed.author_name}")
                
                # Match to Amazon listing
                amazon_match = find_amazon_match(provider, parsed.book_title, parsed.author_name)
                if not amazon_match:
                    self.stdout.write(self.style.WARNING(f"    [FAIL] Could not pair with valid Amazon URL. Skipping."))
                    continue
                    
                amazon_url, asin = amazon_match
                if asin in seen_asins or Book.objects.filter(asin=asin).exists():
                    self.stdout.write(f"    [INFO] Book ASIN {asin} already processed. Skipping duplicate.")
                    continue
                    
                seen_asins.add(asin)
                self.stdout.write(self.style.SUCCESS(f"    [OK] Matched Amazon: {amazon_url} (ASIN: {asin})"))
                
                # Create Book record
                book = Book.objects.create(
                    research_run=run,
                    title=parsed.book_title,
                    author_name=parsed.author_name,
                    asin=asin,
                    amazon_book_url=amazon_url,
                    normalized_key=normalized_book_key(parsed.book_title, parsed.author_name, asin),
                    source_provider="blog_harvester",
                    amazon_source_url=res.url,
                    amazon_source_title=res.title,
                    amazon_source_snippet=res.snippet,
                    is_childrens_book=True,
                    is_picture_or_illustrated_book=True,
                    book_classification_confidence=parsed.confidence,
                    book_classification_reason=parsed.reason
                )
                
                # Enrich and Score Book through lead manager pipeline
                self.stdout.write(f"    [PIPELINE] Running Lead Enrichment Pipeline (crawling, emails, agents, pitches)...")
                try:
                    lead = process_book(
                        book, 
                        run_video_search=not options["no_video_search"], 
                        run_ai_extraction=not options["no_ai"]
                    )
                    
                    if lead and lead.lead_tier != "rejected":
                        leads_processed.append(lead)
                        self.stdout.write(self.style.SUCCESS(
                            f"    [HOT] Lead Generated! Score: {lead.lead_score} ({lead.lead_tier.upper()}) | Contact: {lead.public_email or 'No Direct Email'}"
                        ))
                    else:
                        self.stdout.write(self.style.WARNING(f"    [WARNING] Lead rejected during strict data pipeline validation rules."))
                except Exception as exc:
                    self.stderr.write(f"    [ERROR] Pipeline enrichment failed for book: {exc}")
                    
                # Brief sleep between pipeline iterations to respect rate limits
                time.sleep(1.0)
                
        # Export leads to CSV file
        lead_ids = [l.id for l in leads_processed]
        leads_qs = Lead.objects.filter(id__in=lead_ids).order_by("-lead_score")
        exported_count = export_leads_to_file(leads_qs, str(output_file))
        
        # Output beautiful Lead Manager Dashboard to Console
        self.stdout.write("\n")
        self.stdout.write(self.style.SUCCESS("+----------------------------------------------------------------------------------------+"))
        self.stdout.write(self.style.SUCCESS("|                         KIDLIT BLOG HARVESTER - LEAD DASHBOARD                         |"))
        self.stdout.write(self.style.SUCCESS("+----------------------------------------------------------------------------------------+"))
        self.stdout.write(self.style.SUCCESS(f"| Total Discovered: {len(leads_processed):<3} | Exported Rows: {exported_count:<3} | Destination: {options['output']:<30}  |"))
        self.stdout.write(self.style.SUCCESS("+----------------------------------------------------------------------------------------+"))
        self.stdout.write(self.style.SUCCESS("| SCORE | TIER   | BOOK TITLE                      | AUTHOR          | DIRECT EMAIL      |"))
        self.stdout.write(self.style.SUCCESS("+----------------------------------------------------------------------------------------+"))
        
        for l in leads_qs:
            title_truncated = l.book.title[:30] + "..." if len(l.book.title) > 30 else l.book.title
            author_truncated = l.book.author_name[:15] + "..." if len(l.book.author_name) > 15 else l.book.author_name
            email_field = l.public_email if l.public_email else "-"
            
            self.stdout.write(self.style.SUCCESS(
                f"|  {l.lead_score:<4} | {l.lead_tier.upper():<6} | {title_truncated:<31} | {author_truncated:<15} | {email_field:<17} |"
            ))
            
        self.stdout.write(self.style.SUCCESS("+----------------------------------------------------------------------------------------+"))
        self.stdout.write(self.style.SUCCESS(f"All done! Next-level leads successfully generated and stored. Let's make it happen!\n"))
