from __future__ import annotations

from urllib.parse import urlparse

from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.extract_links import extract_social_links
from leadfinder.utils.source_confidence import clamp_confidence

from .groq_client import GroqJSONClient
from .schemas import ContactExtraction


def extract_contact_data(
    author_name: str,
    book_title: str,
    website_url: str,
    page_url: str,
    visible_text: str,
    links: list[str],
    use_ai: bool = True,
) -> ContactExtraction:
    from leadfinder.services.pipeline.lead_validator import is_valid_email, validate_phone_number, deobfuscate_email, is_highly_valid_contact_email

    # Pre-filter regex extracted contacts using the free validation layer
    emails = []
    for e in extract_emails(visible_text):
        clean_e = deobfuscate_email(e)
        if clean_e and is_highly_valid_contact_email(clean_e) and clean_e not in emails:
            emails.append(clean_e)
    phones = []
    for p in extract_phones(visible_text):
        vp = validate_phone_number(p)
        if vp:
            phones.append(vp)
            
    socials = extract_social_links(links)
    payload = {
        "author_name": author_name,
        "book_title": book_title,
        "website_url": website_url,
        "page_url": page_url,
        "visible_text": visible_text,
        "extracted_regex_emails": emails,
        "extracted_regex_phones": phones,
        "extracted_social_urls": socials,
    }
    prompt = (
        "You are tasked with executing a professional audit of the provided text and links to extract 100% genuine and identity-verified contact information for the author.\n"
        "STRICT IDENTITY PRINCIPLES:\n"
        "1. Direct Author Contacts: The 'public_email' and 'public_phone' MUST belong to the author personally or their official personal book website/brand.\n"
        "2. Representation: Strictly separate literary agent representation info (e.g. 'represented by [Agent Name]', 'rights/subsidiary rights: [Agent Email]') into 'agent_name' and 'representation_email'.\n"
        "3. Publicity & School Bookings: Extract publisher publicity/booking desk contacts into 'publicist_email'.\n"
        "4. DO NOT MIX ROLES: Do not place agent or publisher emails in the direct 'public_email' field.\n"
        "5. REJECT PLATFORMS & SUPPORT: Completely reject and return null for platform/hosting support, tech administrative, and generic retail portals (e.g. any emails at @wordpress.com, @wix.com, @wixsite.com, @blogger.com, @shopify.com, @amazon.com, or prefixes like support@, help@, webmaster@, no-reply@).\n"
        "6. REJECT CATALOG/BOOKSTORE CONTACTS: Never use Open Library, Archive.org, Goodreads, WorldCat, LibraryThing, MIT Press Bookstore, AbeBooks, Bookshop, or retailer/bookstore contact emails/phones as author contacts.\n"
        "7. NO DUMMY PLACEHOLDERS: Always reject placeholder emails (such as author@example.com, info@publisher.com, info@yourdomain.com).\n"
        "Your JSON output MUST contain exactly the following keys with these types:\n"
        "- canonical_website: string (URL) or null\n"
        "- contact_page_url: string (URL) or null\n"
        "- public_email: string (email address) or null (use for direct author email)\n"
        "- public_phone: string (phone number) or null (use for direct author phone)\n"
        "- location: string or null\n"
        "- instagram_url: string (URL) or null\n"
        "- facebook_url: string (URL) or null\n"
        "- tiktok_url: string (URL) or null\n"
        "- youtube_url: string (URL) or null\n"
        "- linkedin_url: string (URL) or null\n"
        "- goodreads_url: string (URL) or null\n"
        "- publisher_url: string (URL) or null\n"
        "- agent_name: string or null (name of the literary agent or booking agency)\n"
        "- representation_email: string (email address) or null (email of the literary agent/agency)\n"
        "- publicist_email: string (email address) or null (email of the publisher's publicist/booking desk)\n"
        "- confidence: float between 0 and 1\n"
        "- warnings: array of strings\n"
        "- evidence: array of objects, where each object contains:\n"
        "  - field: string (the name of the field this evidence is for)\n"
        "  - value: string (the extracted value)\n"
        "  - source_url: string (the URL where this was found)\n"
        "  - confidence: float between 0 and 1\n"
        "  - reason: string (brief explanation of the evidence)"
    )
    ai = GroqJSONClient().complete_json(prompt, payload) if use_ai else None
    
    if ai:
        ext_pub_email = deobfuscate_email(ai.get("public_email")) if ai.get("public_email") else None
        ext_rep_email = deobfuscate_email(ai.get("representation_email")) if ai.get("representation_email") else None
        ext_publ_email = deobfuscate_email(ai.get("publicist_email")) if ai.get("publicist_email") else None
        ext_phone = ai.get("public_phone")
        
        # Apply strict validation layers
        pub_email = ext_pub_email if ext_pub_email and is_highly_valid_contact_email(ext_pub_email) else None
        rep_email = ext_rep_email if ext_rep_email and is_highly_valid_contact_email(ext_rep_email) else None
        publ_email = ext_publ_email if ext_publ_email and is_highly_valid_contact_email(ext_publ_email) else None
        phone = validate_phone_number(ext_phone) if ext_phone else None
        
        # Adjust evidence to drop invalid/filtered contacts
        evidence = []
        for item in (ai.get("evidence") or []):
            field = item.get("field")
            val = item.get("value")
            if not field or not val:
                continue
            if field in {"public_email", "representation_email", "publicist_email"} and not is_highly_valid_contact_email(val):
                continue
            if field == "public_phone" and not validate_phone_number(val):
                continue
            evidence.append(item)
            
        return ContactExtraction(
            canonical_website=ai.get("canonical_website"),
            contact_page_url=ai.get("contact_page_url"),
            public_email=pub_email,
            public_phone=phone,
            location=ai.get("location"),
            instagram_url=ai.get("instagram_url"),
            facebook_url=ai.get("facebook_url"),
            tiktok_url=ai.get("tiktok_url"),
            youtube_url=ai.get("youtube_url"),
            linkedin_url=ai.get("linkedin_url"),
            goodreads_url=ai.get("goodreads_url"),
            publisher_url=ai.get("publisher_url"),
            agent_name=ai.get("agent_name"),
            representation_email=rep_email,
            publicist_email=publ_email,
            confidence=clamp_confidence(ai.get("confidence")),
            warnings=ai.get("warnings") or [],
            evidence=evidence,
        )
        
    host = urlparse(website_url).hostname or ""
    email = emails[0] if emails else None
    phone = phones[0] if phones else None
    evidence = []
    for field, value in {"public_email": email, "public_phone": phone, **socials}.items():
        if value:
            evidence.append(
                {
                    "field": field,
                    "value": value,
                    "source_url": page_url,
                    "confidence": 0.7 if field != "public_phone" else 0.55,
                    "reason": "Found in visible public page text or public link.",
                }
            )
    confidence = 0.65 if email or phone or socials else 0.25
    return ContactExtraction(
        canonical_website=website_url,
        contact_page_url=page_url if "contact" in page_url.lower() else None,
        public_email=email,
        public_phone=phone,
        confidence=confidence,
        warnings=[] if email or phone or socials else [f"No public contact data found on {host}."],
        evidence=evidence,
        **socials,
    )
