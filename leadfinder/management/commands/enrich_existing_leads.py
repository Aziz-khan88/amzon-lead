from __future__ import annotations

from django.core.management.base import BaseCommand
from leadfinder.models import Book, Lead, AuthorProfile
from leadfinder.utils.normalize import is_valid_author_name, normalized_author_key
from leadfinder.services.amazon.amazon_scraper import scrape_amazon_book_page
from leadfinder.services.scoring.lead_score import score_from_lead
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Clean up and enrich missing/incorrect authors in existing books and leads in the database."

    def safe_write(self, msg: str):
        import sys
        try:
            self.stdout.write(msg)
        except UnicodeEncodeError:
            enc = sys.stdout.encoding or 'utf-8'
            self.stdout.write(msg.encode(enc, errors='replace').decode(enc))

    def add_arguments(self, parser):
        parser.add_argument("--asin", help="Optionally enrich a specific book by ASIN")
        parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without saving to the DB")
        parser.add_argument("--force", action="store_true", help="Force re-scraping even if author name is already valid")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        asin = options["asin"]

        if asin:
            books = Book.objects.filter(asin=asin)
            self.safe_write(f"Filtering books for specific ASIN: {asin} (found {books.count()} records)")
        else:
            books = Book.objects.all()
            self.safe_write(f"Scanning all books in database ({books.count()} total records)...")

        # 1. Fast-path backfill for any existing AuthorProfiles missing amazon_author_url but having a valid name
        self.safe_write("Running fast-path backfill for AuthorProfiles with missing Amazon Author URLs...")
        backfill_count = 0
        profiles_to_backfill = AuthorProfile.objects.filter(amazon_author_url="")
        for ap in profiles_to_backfill:
            if is_valid_author_name(ap.author_name):
                ap.amazon_author_url = f"https://www.amazon.com/author/{ap.author_name.replace(' ', '-')}"
                if not dry_run:
                    ap.save()
                backfill_count += 1
        self.safe_write(self.style.SUCCESS(f"Fast-path backfill complete. Updated {backfill_count} profiles."))

        updated_count = 0
        processed_asins = set()

        for book in books:
            # Check if book has missing or invalid author
            has_invalid_author = not is_valid_author_name(book.author_name)
            
            if not has_invalid_author and not force:
                continue

            self.safe_write(f"Found book needing enrichment: ASIN={book.asin}, Title='{book.title[:50]}', Current Author='{book.author_name}'")
            
            if not book.asin:
                self.safe_write(self.style.WARNING(f"Skipping book {book.id} - missing ASIN"))
                continue

            # Avoid re-scraping the same ASIN in the same run; reuse cached successfully scraped data from a previous iteration
            if book.asin in processed_asins:
                cached = Book.objects.filter(asin=book.asin).exclude(author_name="").order_by("-book_data_confidence").first()
                if cached and is_valid_author_name(cached.author_name):
                    self.safe_write(f"  -> Reusing freshly enriched author '{cached.author_name}' for duplicate ASIN {book.asin}")
                    if not dry_run:
                        book.author_name = cached.author_name
                        book.title = cached.title
                        book.review_count = cached.review_count
                        book.rating = cached.rating
                        book.publisher = cached.publisher
                        book.publication_date = cached.publication_date
                        book.cover_image_url = cached.cover_image_url
                        book.has_aplus_content = cached.has_aplus_content
                        book.save()
                        
                        leads = Lead.objects.filter(book=book)
                        for lead in leads:
                            ap = lead.author_profile
                            if ap:
                                ap.author_name = cached.author_name
                                ap.normalized_author_key = normalized_author_key(cached.author_name)
                                if not ap.amazon_author_url:
                                    cached_ap = AuthorProfile.objects.filter(author_name=cached.author_name).exclude(amazon_author_url="").first()
                                    if cached_ap:
                                        ap.amazon_author_url = cached_ap.amazon_author_url
                                    else:
                                        ap.amazon_author_url = f"https://www.amazon.com/author/{cached.author_name.replace(' ', '-')}"
                                ap.save()
                            lead.lead_score, lead.lead_tier = score_from_lead(lead)
                            if lead.manual_review_status == "rejected" and lead.lead_tier != "rejected":
                                lead.manual_review_status = "needs_review"
                            lead.save()
                        updated_count += 1
                    continue

            # Scrape from Amazon using our improved scraper
            try:
                am_res = scrape_amazon_book_page(book.asin, use_ai=True, book_title=book.title)
            except Exception as exc:
                self.safe_write(self.style.ERROR(f"Error scraping ASIN {book.asin}: {exc}"))
                continue

            if am_res and am_res.get("authors"):
                first_author = am_res["authors"][0]
                scraped_author = first_author.get("name", "")
                
                if scraped_author and is_valid_author_name(scraped_author):
                    self.safe_write(self.style.SUCCESS(f"  -> Extracted correct author: '{scraped_author}'"))
                    
                    if dry_run:
                        self.safe_write("  [DRY RUN] Would update book and leads.")
                        continue
                        
                    # Update Book details
                    book.author_name = scraped_author
                    
                    if am_res.get("title"):
                        book.title = am_res["title"]
                    if am_res.get("review_count") is not None:
                        book.review_count = am_res["review_count"]
                    if am_res.get("rating") is not None:
                        book.rating = am_res["rating"]
                    if am_res.get("publisher"):
                        book.publisher = am_res["publisher"]
                    if am_res.get("publication_date"):
                        book.publication_date = am_res["publication_date"]
                    if am_res.get("cover_image_url"):
                        book.cover_image_url = am_res["cover_image_url"]
                    if am_res.get("has_aplus_content") is not None:
                        book.has_aplus_content = am_res["has_aplus_content"]
                        
                    book.save()
                    processed_asins.add(book.asin)
                    updated_count += 1

                    # Update associated leads & author profiles
                    leads = Lead.objects.filter(book=book)
                    for lead in leads:
                        ap = lead.author_profile
                        if ap:
                             ap.author_name = scraped_author
                             ap.normalized_author_key = normalized_author_key(scraped_author)
                             if not ap.amazon_author_url:
                                 if first_author.get("url"):
                                     ap.amazon_author_url = first_author["url"]
                                 elif scraped_author:
                                     ap.amazon_author_url = f"https://www.amazon.com/author/{scraped_author.replace(' ', '-')}"
                             ap.save()
                            
                        # Recalculate lead score and tier now that the author is valid
                        lead.lead_score, lead.lead_tier = score_from_lead(lead)
                        # If lead was rejected previously due to missing author/amazon url, reset status
                        if lead.manual_review_status == "rejected" and lead.lead_tier != "rejected":
                             lead.manual_review_status = "needs_review"
                            
                        lead.save()
                        self.safe_write(f"  -> Updated Lead {lead.id}: Score={lead.lead_score}, Tier={lead.lead_tier}")
                else:
                    self.safe_write(self.style.WARNING(f"  -> Scraped author '{scraped_author}' is still not valid."))
            else:
                self.safe_write(self.style.WARNING("  -> Scraper returned no authors or failed to parse."))

        self.safe_write(self.style.SUCCESS(f"Enrichment run complete. Updated {updated_count} books and their associated leads."))

