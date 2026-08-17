from __future__ import annotations

import logging
import random
import socket
import smtplib
from functools import lru_cache
import dns.resolver
from django.conf import settings
from email_validator import validate_email, EmailNotValidError

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1024)
def get_mx_hosts(domain: str) -> list[str]:
    """
    Performs a DNS lookup for the MX records of a domain.
    Returns a list of MX hosts sorted by preference.
    """
    if not domain:
        return []
    try:
        resolver = dns.resolver.Resolver(configure=True)
        dns_timeout = float(getattr(settings, "APP_DNS_TIMEOUT_SECONDS", 1.0))
        resolver.timeout = dns_timeout
        resolver.lifetime = dns_timeout
        # Ensure fast reliable public DNS resolution fallback
        resolver.nameservers = list(dict.fromkeys(resolver.nameservers + ["8.8.8.8", "1.1.1.1"]))
        
        answers = resolver.resolve(domain, 'MX')
        # Sort answers by preference safely (handles mock strings in unit tests)
        try:
            sorted_answers = sorted(answers, key=lambda mx: getattr(mx, "preference", 0))
            return [str(getattr(mx, "exchange", mx)).rstrip('.') for mx in sorted_answers]
        except Exception:
            return [str(mx).rstrip('.') for mx in answers]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.Timeout) as e:
        logger.debug(f"No MX records found for {domain}: {e}")
        # Try checking for an A record as a fallback
        try:
            resolver = dns.resolver.Resolver(configure=True)
            resolver.timeout = dns_timeout
            resolver.lifetime = dns_timeout
            resolver.nameservers = list(dict.fromkeys(resolver.nameservers + ["8.8.8.8", "1.1.1.1"]))
            a_answers = resolver.resolve(domain, 'A')
            if a_answers:
                return [domain]
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Error resolving MX records for {domain}: {e}")
    return []


def smtp_ping(mx_host: str, recipient: str, sender: str = "verify@leadfinder.com", timeout: float = 2.0) -> tuple[bool | None, str]:
    """
    Connects to the MX host and performs SMTP handshake commands
    (HELO, MAIL FROM, RCPT TO) to check if the mailbox exists.
    
    Returns:
        (is_valid, response_message)
        is_valid can be:
          - True: Mailbox explicitly exists or accepted.
          - False: Mailbox explicitly does not exist (e.g. 550 User Unknown).
          - None: Undetermined due to network/firewall timeouts or connection failures.
    """
    try:
        # Resolve the MX host IP to verify connectivity and enforce timeout
        socket.gethostbyname(mx_host)
        
        # Connect to port 25 (standard SMTP)
        with smtplib.SMTP(mx_host, port=25, timeout=timeout) as smtp:
            # Say hello to the SMTP server
            smtp.helo()
            
            # Send MAIL FROM
            code, message = smtp.mail(sender)
            if code != 250:
                return None, f"SMTP MAIL FROM failed: {code} {message.decode('utf-8', errors='ignore')}"
            
            # Send RCPT TO
            code, message_bytes = smtp.rcpt(recipient)
            message = message_bytes.decode('utf-8', errors='ignore')
            
            if code == 250:
                return True, f"Deliverable (250): {message}"
            elif code == 251:
                return True, f"Deliverable (251 User not local; will forward): {message}"
            elif code >= 500:
                # 550 is the standard 'Mailbox unavailable' error
                return False, f"Undeliverable ({code}): {message}"
            elif code == 450 or code == 451 or code == 452:
                # Temporary failures (e.g. greylisting or mailbox full)
                return True, f"Greylisted/Temp-Blocked ({code}): {message}"
            else:
                return True, f"SMTP response code {code}: {message}"
    except (socket.timeout, socket.error) as e:
        logger.debug(f"SMTP connection timeout/error to {mx_host}: {e}")
        return None, f"Network timeout/connection error: {e}"
    except Exception as e:
        logger.debug(f"SMTP ping exception on {mx_host}: {e}")
        return None, f"SMTP Ping error: {e}"

def is_catch_all(mx_host: str, domain: str, sender: str = "verify@leadfinder.com", timeout: float = 2.0) -> bool:
    """
    Checks if the destination SMTP server is a catch-all server
    (meaning it accepts all mailboxes, even non-existent ones).
    """
    random_mailbox = f"nonexistent_random_mailbox_{random.randint(10000, 99999)}@{domain}"
    valid, _ = smtp_ping(mx_host, random_mailbox, sender, timeout)
    return valid is True

@lru_cache(maxsize=2048)
def check_deliverability(email: str, sender: str = "verify@leadfinder.com") -> dict[str, any]:
    """
    Performs full syntax validation, DNS MX record checking, SMTP handshakes,
    and catch-all detection for an email address.
    
    Returns a dictionary of deliverability audit details:
    {
        "email": str,
        "syntax_valid": bool,
        "status": "deliverable" | "undeliverable" | "catch_all" | "unknown",
        "mx_hosts": list[str],
        "message": str
    }
    """
    result = {
        "email": email,
        "syntax_valid": False,
        "status": "unknown",
        "mx_hosts": [],
        "message": ""
    }
    
    if not email:
        result["message"] = "Empty email address provided."
        return result
        
    # 1. Syntax check
    try:
        valid = validate_email(email.strip(), check_deliverability=False)
        email_clean = valid.ascii_email
        domain = valid.domain
        result["syntax_valid"] = True
    except EmailNotValidError as e:
        result["status"] = "undeliverable"
        result["message"] = f"Invalid email syntax: {e}"
        return result
        
    # 2. DNS MX records lookup
    mx_hosts = get_mx_hosts(domain)
    result["mx_hosts"] = mx_hosts
    if not mx_hosts:
        result["status"] = "undeliverable"
        result["message"] = f"No MX or A records resolved for domain: {domain}"
        return result
        
    # 3. SMTP Ping on top MX host
    primary_mx = mx_hosts[0]
    
    # We perform the catch-all check first, because if it's a catch-all, any mailbox is 'valid'
    catch_all_active = False
    try:
        catch_all_active = is_catch_all(primary_mx, domain, sender)
    except Exception:
        pass
        
    if catch_all_active:
        result["status"] = "catch_all"
        result["message"] = f"Domain {domain} is a catch-all server. All addresses are accepted."
        return result
        
    # Standard mailbox check
    valid, msg = smtp_ping(primary_mx, email_clean, sender)
    result["message"] = msg
    
    if valid is True:
        result["status"] = "deliverable"
    elif valid is False:
        result["status"] = "undeliverable"
    else:
        # None returned (network issue, port 25 blocked, etc.)
        result["status"] = "unknown"
        result["message"] = f"Network or firewall restricted port 25 checking: {msg}"
        
    return result
