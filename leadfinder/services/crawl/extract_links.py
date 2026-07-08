from __future__ import annotations

import warnings
from urllib.parse import urljoin

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


SOCIAL_DOMAINS = {
    "instagram.com": "instagram_url",
    "facebook.com": "facebook_url",
    "tiktok.com": "tiktok_url",
    "youtube.com": "youtube_url",
    "youtu.be": "youtube_url",
    "linkedin.com": "linkedin_url",
    "goodreads.com": "goodreads_url",
}


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = urljoin(base_url, tag["href"].strip())
        if href.startswith(("http://", "https://")) and href not in links:
            links.append(href)
    return links


def extract_social_links(links: list[str]) -> dict[str, str]:
    socials: dict[str, str] = {}
    for link in links:
        lower = link.lower()
        for domain, field in SOCIAL_DOMAINS.items():
            if domain in lower and field not in socials:
                socials[field] = link
    return socials
