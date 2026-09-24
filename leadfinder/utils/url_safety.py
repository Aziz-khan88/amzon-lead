from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse


BLOCKED_PATH_PARTS = {
    "admin",
    "login",
    "signin",
    "account",
    "cart",
    "checkout",
    "wp-admin",
    "dashboard",
}


def is_safe_public_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "0.0.0.0"} or host.startswith("127."):
        return False
    path_parts = {part.lower() for part in parsed.path.split("/") if part}
    if path_parts & BLOCKED_PATH_PARTS:
        return False
    return not _host_resolves_private(host)


@lru_cache(maxsize=2048)
def _host_resolves_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # Unresolvable hosts cannot be fetched anyway; the request layer fails.
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False
