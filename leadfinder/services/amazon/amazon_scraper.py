from __future__ import annotations

import json
import logging
import os
import random
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from leadfinder.services.ai.groq_client import GroqJSONClient
from leadfinder.services.search import get_search_provider
from leadfinder.utils.source_confidence import clamp_confidence
from leadfinder.utils.normalize import is_valid_author_name, clean_author_name, extract_authors_from_colon_format, normalize_text

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edge/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


def get_random_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Cache-Control": "max-age=0",
    }


def is_blocked(soup: BeautifulSoup) -> bool:
    title = soup.title.string.lower() if soup.title else ""
    text = soup.get_text().lower()
    return (
        "robot check" in title or
        "captcha" in title or
        "enter the characters you see below" in text or
        "sorry, we just need to make sure you're not a robot" in text
    )


def extract_rating(text: str) -> float | None:
    match = re.search(r"([0-9.]+)\s*(?:out of|stars?)", text, re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def extract_review_count(text: str) -> int | None:
    # Match patterns like: "1,234 reviews", "45 ratings", "120 customer reviews", etc.
    match = re.search(r"([0-9,]+)\s*(?:ratings?|reviews?|customer reviews?|stars?)", text, re.I)
    if match:
        cleaned = re.sub(r"[^0-9]", "", match.group(1))
        if cleaned:
            try:
                val = int(cleaned)
                if val < 10000000:
                    return val
            except ValueError:
                pass
    
    # Fallback to simple number extraction ONLY if the text is short (like "45" or "1,234")
    # to maintain compatibility with raw strings.
    if len(text.strip()) < 15:
        cleaned = re.sub(r"[^0-9]", "", text)
        if cleaned:
            try:
                val = int(cleaned)
                if val < 10000000:
                    return val
            except ValueError:
                pass
                
    return None


def fetch_metadata_from_free_apis(asin: str) -> dict | None:
    """
    Attempts to fetch book metadata from free API providers (Open Library and Google Books) using ASIN as ISBN.
    Returns a dict with scraped fields if successful, otherwise None.
    """
    # Verify the ASIN looks like a standard ISBN-10 (10 chars, can end with X/x) or ISBN-13
    clean_asin = re.sub(r"[^0-9Xx]", "", asin)
    if len(clean_asin) not in (10, 13):
        return None

    # 1. Try Open Library API
    url_ol = f"https://openlibrary.org/api/books?bibkeys=ISBN:{clean_asin}&format=json&jscmd=data"
    try:
        response = requests.get(url_ol, timeout=10)
        if response.status_code == 200:
            data = response.json()
            key = f"ISBN:{clean_asin}"
            if key in data:
                info = data[key]
                authors = []
                for author_data in info.get("authors", []):
                    name = author_data.get("name")
                    if name and is_valid_author_name(name):
                        authors.append({"name": name, "url": author_data.get("url", "")})
                
                if authors:
                    # Successfully found book details
                    title = info.get("title", "")
                    publisher = ""
                    publishers = info.get("publishers", [])
                    if publishers:
                        publisher = publishers[0].get("name", "")
                    
                    cover_image_url = ""
                    cover_data = info.get("cover", {})
                    if cover_data:
                        cover_image_url = cover_data.get("large") or cover_data.get("medium") or cover_data.get("small") or ""

                    description = ""
                    excerpts = info.get("excerpts", [])
                    if excerpts:
                        description = excerpts[0].get("text", "")
                    elif "notes" in info:
                        description = info["notes"]

                    return {
                        "title": title,
                        "authors": authors,
                        "publisher": publisher,
                        "publication_date": info.get("publish_date", ""),
                        "cover_image_url": cover_image_url,
                        "description": description,
                        "scraped_successfully": True,
                    }
    except Exception as exc:
        logger.warning(f"Error fetching from Open Library for ASIN {asin}: {exc}")

    # 2. Try Google Books API (free public endpoint)
    url_gb = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_asin}"
    try:
        response = requests.get(url_gb, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "items" in data:
                volume_info = data["items"][0]["volumeInfo"]
                authors = []
                for author_name in volume_info.get("authors", []):
                    if author_name and is_valid_author_name(author_name):
                        authors.append({"name": author_name, "url": ""})
                
                if authors:
                    title = volume_info.get("title", "")
                    publisher = volume_info.get("publisher", "")
                    cover_image_url = ""
                    image_links = volume_info.get("imageLinks", {})
                    if image_links:
                        cover_image_url = image_links.get("extraLarge") or image_links.get("large") or image_links.get("medium") or image_links.get("small") or image_links.get("thumbnail") or ""

                    return {
                        "title": title,
                        "authors": authors,
                        "publisher": publisher,
                        "publication_date": volume_info.get("publishedDate", ""),
                        "cover_image_url": cover_image_url,
                        "description": volume_info.get("description", ""),
                        "scraped_successfully": True,
                    }
    except Exception as exc:
        logger.warning(f"Error fetching from Google Books for ASIN {asin}: {exc}")

    return None


def scrape_amazon_book_page(asin: str, use_ai: bool = True, book_title: str = "") -> dict:
    url = f"https://www.amazon.com/dp/{asin}"
    result = {
        "asin": asin,
        "title": "",
        "authors": [],  # list of dicts: {"name": str, "url": str}
        "rating": None,
        "review_count": None,
        "publisher": "",
        "publication_date": "",
        "cover_image_url": "",
        "description": "",
        "has_aplus_content": False,
        "scraped_successfully": False,
        "source": url,
    }

    try:
        response = requests.get(url, headers=get_random_headers(), timeout=15)
        soup = BeautifulSoup(response.content, "html.parser")
        
        if response.status_code == 200 and not is_blocked(soup):
            result["scraped_successfully"] = True

            # A+ Content Detection
            aplus_node = soup.select_one(".aplus-v2, #aplus, #aplus_feature_div")
            result["has_aplus_content"] = aplus_node is not None

            # Title
            title_node = soup.select_one("#productTitle")
            if title_node:
                result["title"] = title_node.get_text(strip=True)

            # Authors & Contributors
            raw_creators = []
            
            # 1. Byline links
            byline = soup.find(id="bylineInfo")
            if byline:
                for link in byline.find_all("a"):
                    href = link.get("href", "")
                    text = link.get_text(strip=True)
                    if text:
                        raw_creators.append((text, href))
            
            # 2. Add other elements if they match selector
            for link in soup.select("a.contributorNameID, a.author-link, .author .a-link-normal, .contributorNameLink"):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if text and (text, href) not in raw_creators:
                    raw_creators.append((text, href))
                    
            for text, href in raw_creators:
                cleaned = clean_author_name(text)
                if is_valid_author_name(cleaned):
                    author_url = ""
                    if href:
                        if href.startswith("/"):
                            author_url = f"https://www.amazon.com{href}"
                        else:
                            author_url = href
                    # Avoid adding duplicates
                    if not any(a["name"] == cleaned for a in result["authors"]):
                        result["authors"].append({"name": cleaned, "url": author_url})

            rating_node = soup.select_one("span.a-icon-alt")
            if rating_node:
                result["rating"] = extract_rating(rating_node.get_text(strip=True))

            # Review Count
            reviews_node = soup.select_one("#acrCustomerReviewText")
            if reviews_node:
                result["review_count"] = extract_review_count(reviews_node.get_text(strip=True))

            # Description
            desc_node = soup.select_one("#bookDescription_feature_div .a-expander-content, #bookDescription_feature_div")
            if desc_node:
                result["description"] = desc_node.get_text(" ", strip=True)

            # Cover Image
            img_node = soup.select_one("#imgBlkFront, #landingImage, #imageBlockOuter img")
            if img_node:
                result["cover_image_url"] = img_node.get("src", img_node.get("data-a-dynamic-image", ""))
                # If dynamic image is a dict, parse it
                if result["cover_image_url"].startswith("{"):
                    try:
                        urls = list(json.loads(result["cover_image_url"]).keys())
                        if urls:
                            result["cover_image_url"] = urls[0]
                    except Exception:
                        pass

            # Publisher and publication date
            bullets = soup.select("#detailBullets_feature_div li, #productDetails_db_sections tr")
            for bullet in bullets:
                text = bullet.get_text(" ", strip=True)
                if "publisher" in text.lower():
                    # Format: Publisher : Knopf Books for Young Readers (September 13, 2005)
                    parts = text.split(":")
                    if len(parts) > 1:
                        val = parts[1].strip()
                        # Extract date in parentheses if exists
                        date_match = re.search(r"\(([^)]+)\)", val)
                        if date_match:
                            result["publication_date"] = date_match.group(1).strip()
                            result["publisher"] = re.sub(r"\([^)]+\)", "", val).strip()
                        else:
                            result["publisher"] = val
                elif "publication date" in text.lower() or "release date" in text.lower():
                    parts = text.split(":")
                    if len(parts) > 1:
                        result["publication_date"] = parts[1].strip()

        else:
            logger.warning(f"Amazon product page direct fetch blocked or failed with status {response.status_code} for ASIN {asin}.")
    except Exception as exc:
        logger.error(f"Error scraping Amazon product page direct fetch: {exc}")

    # Fallback to free book APIs (Open Library & Google Books) first if direct scrape is incomplete/failed/blocked
    if not result.get("scraped_successfully") or not result.get("authors"):
        logger.info(f"Direct Amazon scraping incomplete or blocked. Trying free book APIs for ASIN {asin}")
        api_data = fetch_metadata_from_free_apis(asin)
        if api_data:
            result.update(api_data)

    # Fallback to search engines if both direct scrape and free APIs failed
    if not result.get("scraped_successfully") or not result.get("authors"):
        logger.info(f"Triggering search engine and AI fallback for ASIN {asin}")
        fallback_data = fallback_amazon_book_page(asin, use_ai=use_ai, book_title=book_title)
        result.update(fallback_data)

    return result


def run_ai_extraction_on_results(results, asin: str) -> dict | None:
    snippets = []
    for r in results:
        snippets.append(f"Title: {r.title}\nSnippet: {r.snippet or ''}\nURL: {r.url}")
    combined_text = "\n\n".join(snippets)
    if not combined_text:
        return None

    try:
        prompt = (
            "Extract detailed book metadata from these search result snippets for Amazon page of ASIN " + asin + ".\n"
            "Return exactly this JSON format:\n"
            "{\n"
            '  "title": "string or empty",\n'
            '  "authors": [{"name": "string", "url": "string or empty"}],\n'
            '  "rating": float or null,\n'
            '  "review_count": integer or null,\n'
            '  "publisher": "string or empty",\n'
            '  "publication_date": "string or empty",\n'
            '  "description": "string or empty",\n'
            '  "cover_image_url": "string or empty"\n'
            "}"
        )
        ai_data = GroqJSONClient().complete_json(prompt, {"search_results": combined_text})
        if ai_data:
            # Validate extracted authors
            if "authors" in ai_data and isinstance(ai_data["authors"], list):
                valid_authors = []
                for auth in ai_data["authors"]:
                    if isinstance(auth, dict) and auth.get("name"):
                        name = clean_author_name(auth["name"])
                        if is_valid_author_name(name):
                            valid_authors.append({"name": name, "url": auth.get("url", "")})
                ai_data["authors"] = valid_authors
            return ai_data
    except Exception as exc:
        logger.warning(f"Error in Groq fallback extraction for ASIN {asin}: {exc}")
    return None


def extract_metadata_from_results(results, asin: str, book_title: str = "") -> dict:
    extracted = {
        "title": "",
        "authors": [],
        "rating": None,
        "review_count": None,
        "publisher": "",
        "publication_date": "",
        "description": "",
    }
    if not results:
        return extracted

    # Title guess
    first_title = results[0].title
    # Clean up standard search title format
    first_title = re.sub(r"\s*[:|-]\s*Amazon\..*$", "", first_title, flags=re.I)
    first_title = re.sub(r"\s*\([^)]*Paperback[^)]*\)", "", first_title, flags=re.I)
    extracted["title"] = first_title.split(":")[0].split("by")[0].strip()

    # Rating & reviews regex from snippet
    for text in [r.snippet or "" for r in results] + [r.title for r in results]:
        if not extracted["rating"]:
            extracted["rating"] = extract_rating(text)
        if not extracted["review_count"]:
            extracted["review_count"] = extract_review_count(text)

    # 1. Author guess - check colon format first!
    for r in results:
        colon_authors = extract_authors_from_colon_format(r.title)
        for ca in colon_authors:
            cleaned = clean_author_name(ca)
            if is_valid_author_name(cleaned):
                # Ensure it's not the book title
                if book_title:
                    norm_cand = normalize_text(cleaned)
                    norm_title = normalize_text(book_title)
                    if norm_cand in norm_title or norm_title in norm_cand:
                        continue
                if not any(a["name"] == cleaned for a in extracted["authors"]):
                    extracted["authors"].append({"name": cleaned, "url": ""})

    # 2. Fallback to searching snippets and titles for 'by [Capitalized Name]'
    if not extracted["authors"]:
        for text in [r.snippet or "" for r in results] + [r.title for r in results]:
            # Regex to find 'by [Name]'
            for match in re.finditer(r"\bby\s+([A-Z][a-zA-Z.'-]{1,30}(?:\s+[A-Z][a-zA-Z.'-]{1,30}){1,3})", text):
                cand = clean_author_name(match.group(1))
                if is_valid_author_name(cand):
                    if book_title:
                        norm_cand = normalize_text(cand)
                        norm_title = normalize_text(book_title)
                        if norm_cand in norm_title or norm_title in norm_cand:
                            continue
                    if not any(a["name"] == cand for a in extracted["authors"]):
                        extracted["authors"].append({"name": cand, "url": ""})
                        break
            if extracted["authors"]:
                break

    # 3. Heuristic: Check if the title starts with a capitalized name sequence before standard separators
    if not extracted["authors"]:
        for r in results:
            title_clean = re.split(r"\s+[-|(|:|;]\s+", r.title)[0].strip()
            match = re.match(r"^([A-Z][a-zA-Z.'-]{1,30}(?:\s+[A-Z][a-zA-Z.'-]{1,30}){1,3})$", title_clean)
            if match:
                cand = clean_author_name(match.group(1))
                if is_valid_author_name(cand):
                    if book_title:
                        norm_cand = normalize_text(cand)
                        norm_title = normalize_text(book_title)
                        if norm_cand in norm_title or norm_title in norm_cand:
                            continue
                    if not any(a["name"] == cand for a in extracted["authors"]):
                        extracted["authors"].append({"name": cand, "url": ""})
                        break

    # 4. Heuristic: Check if snippet starts with "[Name] is a/an ..."
    if not extracted["authors"]:
        for r in results:
            snippet = (r.snippet or "").strip()
            match = re.match(r"^([A-Z][a-zA-Z.'-]{1,30}(?:\s+[A-Z][a-zA-Z.'-]{1,30}){1,3})\s+is\s+(?:a|an)\s+", snippet, re.I)
            if match:
                cand = clean_author_name(match.group(1))
                if is_valid_author_name(cand):
                    if book_title:
                        norm_cand = normalize_text(cand)
                        norm_title = normalize_text(book_title)
                        if norm_cand in norm_title or norm_title in norm_cand:
                            continue
                    if not any(a["name"] == cand for a in extracted["authors"]):
                        extracted["authors"].append({"name": cand, "url": ""})
                        break

    return extracted



def fallback_amazon_book_page(asin: str, use_ai: bool = True, book_title: str = "") -> dict:
    fallback_res = {
        "title": "",
        "authors": [],
        "rating": None,
        "review_count": None,
        "publisher": "",
        "publication_date": "",
        "description": "",
        "cover_image_url": "",
        "source": f"https://www.amazon.com/dp/{asin}",
    }
    
    try:
        provider = get_search_provider()
        
        # --- ATTEMPT 1: Target site:amazon.com for ASIN ---
        logger.info(f"Fallback Attempt 1: site:amazon.com {asin}")
        query1 = f"site:amazon.com {asin}"
        results1 = provider.search(query1, max_results=3)
        results1 = [r for r in results1 if "amazon." in r.url.lower()]
        
        if results1:
            extracted = extract_metadata_from_results(results1, asin, book_title)
            for k, v in extracted.items():
                if v:
                    fallback_res[k] = v
                    
        # If author found, try AI first if requested, then return
        if fallback_res.get("authors"):
            if use_ai and GroqJSONClient().available:
                ai_data = run_ai_extraction_on_results(results1, asin)
                if ai_data:
                    return ai_data
            return fallback_res

        # --- ATTEMPT 2: Target the ASIN globally across book catalogs and high-trust domains ---
        logger.info(f"Fallback Attempt 2: Global ASIN search for {asin}")
        query2 = f"{asin}"
        results2 = provider.search(query2, max_results=5)
        
        book_keywords = [
            "book", "author", "illustrator", "novel", "literature", "reading", "paperback", 
            "hardcover", "asin", "isbn", "illustrated", "fiction", "series", "set", "publisher", 
            "goodreads", "fantasticfiction", "barnes", "noble", "library"
        ]
        valid_results2 = []
        for r in results2:
            url_lower = r.url.lower()
            title_lower = r.title.lower()
            snippet_lower = (r.snippet or "").lower()
            is_valid = (
                "amazon." in url_lower
                or asin.lower() in url_lower
                or asin.lower() in title_lower
                or asin.lower() in snippet_lower
                or any(domain in url_lower for domain in [
                    "goodreads.com", "fantasticfiction.com", "fantasticfiction.co.uk", 
                    "barnesandnoble.com", "books.google.com", "librarything.com", "openlibrary.org"
                ])
                or any(kw in url_lower or kw in title_lower or kw in snippet_lower for kw in book_keywords)
            )
            if is_valid:
                valid_results2.append(r)
                
        if valid_results2:
            extracted = extract_metadata_from_results(valid_results2, asin, book_title)
            for k, v in extracted.items():
                if v and not fallback_res.get(k):
                    fallback_res[k] = v
                    
        if fallback_res.get("authors"):
            if use_ai and GroqJSONClient().available:
                ai_data = run_ai_extraction_on_results(valid_results2, asin)
                if ai_data:
                    return ai_data
            return fallback_res

        # --- ATTEMPT 3: Target Book Title (if provided) with 'author' keywords ---
        if book_title and book_title.lower() != "missing" and book_title.lower() != "unknown":
            logger.info(f"Fallback Attempt 3: Search using book title: {book_title} author")
            clean_search_title = re.sub(r"\s*[:|-]\s*Amazon\..*$", "", book_title, flags=re.I)
            clean_search_title = re.sub(r"\s*\([^)]*Paperback[^)]*\)", "", clean_search_title, flags=re.I)
            clean_search_title = clean_search_title.strip(" -:|")
            
            query3 = f"{clean_search_title} author"
            results3 = provider.search(query3, max_results=5)
            
            if results3:
                extracted = extract_metadata_from_results(results3, asin, book_title)
                for k, v in extracted.items():
                    if v and not fallback_res.get(k):
                        fallback_res[k] = v
                        
            if fallback_res.get("authors"):
                if use_ai and GroqJSONClient().available:
                    ai_data = run_ai_extraction_on_results(results3, asin)
                    if ai_data:
                        return ai_data
                return fallback_res

    except Exception as exc:
        logger.error(f"Error in Amazon book fallback parsing: {exc}")
        
    return fallback_res


def scrape_amazon_author_page(url_or_slug: str, use_ai: bool = True) -> dict:
    if not url_or_slug:
        return {}

    url = url_or_slug
    if not url.startswith("http"):
        # Assume it's a slug/name or ID
        if "/" in url_or_slug or url_or_slug.startswith("B0"):
            url = f"https://www.amazon.com/author/{url_or_slug}"
        else:
            url = f"https://www.amazon.com/author/{url_or_slug.replace(' ', '-')}"

    result = {
        "amazon_author_url": url,
        "author_bio": "",
        "author_image_url": "",
        "other_books": [],  # list of strings or dicts
        "scraped_successfully": False,
    }

    try:
        response = requests.get(url, headers=get_random_headers(), timeout=15)
        soup = BeautifulSoup(response.content, "html.parser")
        
        if response.status_code == 200 and not is_blocked(soup):
            result["scraped_successfully"] = True

            # Bio
            bio_node = soup.select_one("#authorBio, #ap-bio, .ap-bio-content, .author-bio, #ap-author-bio")
            if bio_node:
                result["author_bio"] = bio_node.get_text(" ", strip=True)

            # Profile Photo
            img_node = soup.select_one("#ap-author-image, .ap-author-image, #author-image, img.ap-author-image")
            if img_node:
                result["author_image_url"] = img_node.get("src", "")

            # Other Books
            for book_node in soup.select(".ap-book-title, #ap-books-list a, .ap-book-card"):
                title = book_node.get_text(strip=True)
                if title and title not in result["other_books"]:
                    result["other_books"].append(title)
            
            # Fallback books from list elements
            if not result["other_books"]:
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    title = link.get_text(strip=True)
                    if title and ("/dp/" in href or "/product/" in href) and len(title) > 3:
                        if title not in result["other_books"] and not any(term in title.lower() for term in ["amazon", "privacy", "help", "terms"]):
                            result["other_books"].append(title)

        else:
            logger.warning(f"Amazon author page fetch blocked or failed with status {response.status_code} for URL {url}.")
    except Exception as exc:
        logger.error(f"Error scraping Amazon author page direct fetch: {exc}")

    # Fallback if direct scrapers failed
    if not result["scraped_successfully"]:
        logger.info(f"Triggering search engine and AI fallback for Author URL {url}")
        fallback_data = fallback_amazon_author_page(url, use_ai=use_ai)
        result.update(fallback_data)

    return result


def fallback_amazon_author_page(url: str, use_ai: bool = True) -> dict:
    fallback_res = {
        "author_bio": "",
        "author_image_url": "",
        "other_books": [],
    }

    try:
        # Extract author name from URL
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        author_slug = ""
        if len(path_parts) > 1:
            author_slug = path_parts[-1]
        
        author_name = author_slug.replace("-", " ").replace("_", " ").title()
        if not author_name or len(author_name) < 2:
            author_name = "Amazon Author"

        provider = get_search_provider()
        query = f'site:amazon.com/author OR site:amazon.com/wd/e/ "{author_name}"'
        results = provider.search(query, max_results=3)

        if not results:
            query = f'amazon author page "{author_name}" bio'
            results = provider.search(query, max_results=3)

        if not results:
            return fallback_res

        snippets = []
        for r in results:
            snippets.append(f"Title: {r.title}\nSnippet: {r.snippet or ''}\nURL: {r.url}")

        combined_text = "\n\n".join(snippets)

        # 1. Groq AI Extraction Fallback
        if use_ai and GroqJSONClient().available:
            prompt = (
                "Extract the author biography, profile image URL (if mentioned), and other books authored "
                "from these search result snippets for Amazon Author Page: " + url + ".\n"
                "Return exactly this JSON format:\n"
                "{\n"
                '  "author_bio": "string or empty",\n'
                '  "author_image_url": "string or empty",\n'
                '  "other_books": ["string book title", "string book title"]\n'
                "}"
            )
            ai_data = GroqJSONClient().complete_json(prompt, {"search_results": combined_text})
            if ai_data:
                for k in fallback_res:
                    if k in ai_data and ai_data[k]:
                        fallback_res[k] = ai_data[k]
                return fallback_res

        # 2. Heuristic/Regex Fallback
        bios = []
        books = []
        for r in results:
            if r.snippet:
                # Basic heuristics to split sentence and look for bio-like patterns
                bios.append(r.snippet)
                # Try finding book titles (capitalized words in quotes or after written by)
                book_matches = re.findall(r'"([^"]+)"', r.snippet)
                for bm in book_matches:
                    if len(bm) > 4 and bm not in books:
                        books.append(bm)

        fallback_res["author_bio"] = " ".join(bios[:2])
        fallback_res["other_books"] = books[:4]

    except Exception as exc:
        logger.error(f"Error in Amazon author fallback parsing: {exc}")

    return fallback_res
