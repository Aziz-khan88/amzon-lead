from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


def can_fetch_url(url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    try:
        response = requests.get(robots_url, timeout=5, headers={"User-Agent": user_agent})
        if response.status_code >= 400:
            return True
        parser.parse(response.text.splitlines())
        return parser.can_fetch(user_agent, url)
    except Exception:
        return True
