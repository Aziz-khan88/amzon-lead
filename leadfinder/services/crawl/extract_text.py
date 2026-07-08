from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_page_title(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def extract_meta_description(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    return (tag.get("content") or "").strip() if tag else ""
