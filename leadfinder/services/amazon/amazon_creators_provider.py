from __future__ import annotations

import logging
import os
from leadfinder.services.search import get_search_provider
from leadfinder.services.amazon.amazon_url_parser import is_amazon_url, extract_asin, normalize_amazon_book_url
from leadfinder.services.amazon.amazon_scraper import scrape_amazon_book_page

logger = logging.getLogger(__name__)


class AmazonCreatorsProvider:
    """Next-level, free Amazon Creators provider.
    
    Discovers children's books and creator/author details by searching Amazon product pages 
    via public search engine index query mappings and scraping their full product details.
    """

    provider_name = "amazon_creators"

    def is_configured(self) -> bool:
        return True

    def discover_books(self, keyword: str, max_books: int = 25) -> list[dict]:
        logger.info(f"AmazonCreatorsProvider discovering books for keyword: {keyword}")
        
        provider = get_search_provider()
        
        # Build search queries to discover Amazon product links
        queries = [
            f'site:amazon.com/dp "{keyword}" "by"',
            f'site:amazon.com "{keyword}" "paperback" "by"',
            f'site:amazon.com "{keyword}" "picture book" "by"',
            f'site:amazon.com "{keyword}" "illustrator" "by"',
        ]
        
        candidates = []
        seen_asins = set()
        
        for query in queries:
            try:
                results = provider.search(query, max_results=15)
                for dto in results:
                    if not is_amazon_url(dto.url):
                        continue
                    
                    asin = extract_asin(dto.url)
                    if not asin or asin in seen_asins:
                        continue
                        
                    seen_asins.add(asin)
                    logger.info(f"Discovered ASIN {asin} from query: {query}. Scraping details...")
                    
                    # Scrape full details from Amazon product page
                    book_details = scrape_amazon_book_page(asin)
                    
                    title = book_details.get("title") or dto.title.split(":")[0].split("by")[0].strip()
                    author_name = ""
                    if book_details.get("authors"):
                        author_name = book_details["authors"][0]["name"]
                    
                    # Add to candidates
                    normalized_url = normalize_amazon_book_url(dto.url, os.getenv("AMAZON_ASSOCIATE_TAG") or None)
                    candidates.append({
                        "title": title[:500],
                        "author_name": author_name[:255],
                        "asin": asin,
                        "amazon_book_url": normalized_url,
                        "amazon_source_url": dto.url,
                        "amazon_source_title": dto.title,
                        "amazon_source_snippet": dto.snippet or "",
                        "book_data_confidence": 0.9 if book_details.get("scraped_successfully") else 0.5,
                        "source_provider": self.provider_name,
                        "source_raw_json": {
                            "query": query,
                            "rank": dto.rank,
                            "reviews": book_details.get("review_count"),
                            "rating": book_details.get("rating"),
                            "publisher": book_details.get("publisher"),
                            "publication_date": book_details.get("publication_date"),
                            "description": book_details.get("description", "")[:1000]
                        }
                    })
                    
                    if len(candidates) >= max_books:
                        break
            except Exception as exc:
                logger.error(f"Error executing discovery query '{query}': {exc}")
                
            if len(candidates) >= max_books:
                break
                
        return candidates
