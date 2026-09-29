from __future__ import annotations

from datetime import date
import re


def _truthy(data: dict, key: str) -> bool:
    return bool(data.get(key))


def _email_matches_domain(email: str | None, website: str | None) -> bool:
    if not email or not website:
        return False
    email_parts = email.lower().split("@")
    if len(email_parts) < 2:
        return False
    email_domain = email_parts[1].strip()
    if email_domain in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "mail.com", "msn.com", "proton.me", "protonmail.com"]:
        return False
    web_domain = website.lower()
    if "://" in web_domain:
        web_domain = web_domain.split("://")[1]
    web_domain = web_domain.split("/")[0]
    web_domain = re.sub(r"^www\.", "", web_domain).strip()
    return email_domain == web_domain or email_domain in web_domain or web_domain in email_domain


def _publication_recency_points(pub_date: str | None) -> int:
    if not pub_date:
        return 0
    match = re.search(r"(20\d{2})", pub_date)
    if not match:
        return 0
    years_ago = date.today().year - int(match.group(1))
    if years_ago <= 1:
        return 10
    elif years_ago <= 2:
        return 8
    elif years_ago <= 5:
        return 5
    return 0


def score_lead(data: dict) -> tuple[int, str, list[str]]:
    """
    Computes a 100-point score for Children's Picture Book and Illustrated Book Leads following the SOP.
    Returns (score, tier, service_needs_tags).
    """
    score = 0
    service_needs = []

    # Exclusions/Suppressions Check First
    if data.get("do_not_contact") is True:
        return 0, "rejected", []

    # Traditional Publisher Check
    publisher = (data.get("publisher") or "").lower()
    trad_publishers = [
        "scholastic", "harpercollins", "penguin", "knopf", "viking", "crown", 
        "macmillan", "farrar, straus", "roaring brook", "henry holt", "simon & schuster", 
        "hachette", "little, brown", "orchard", "disney", "candlewick", "chronicle", "bloomsbury"
    ]
    is_traditional = False
    if publisher:
        for pub in trad_publishers:
            if pub in publisher:
                is_traditional = True
                break

    if is_traditional:
        return 0, "rejected", []

    # 1. Children's Book / Illustration Fit (Max 20 points)
    is_childrens = data.get("is_childrens_book")
    is_picture_illustrated = data.get("is_picture_or_illustrated_book")

    if is_childrens is False:
        # Severe penalty if explicitly classified as not a children's book
        return 0, "rejected", []

    if is_childrens is True:
        if is_picture_illustrated is True:
            score += 20
        else:
            score += 10

    # 2. Self-published / Indie decision-maker likelihood (Max 20 points)
    # If not a traditional publisher, it is a highly probable indie/self-published lead
    score += 20

    # 3. Visible Service Needs (Max 25 points, 5 pts per need)
    rating = data.get("rating")
    desc = data.get("description") or ""
    has_aplus = data.get("has_aplus_content") is True
    amazon_author_url = data.get("amazon_author_url") or ""
    bio = data.get("author_bio") or ""
    website = data.get("canonical_website") or ""
    video_status = data.get("video_status") or "not_checked"
    other_books = data.get("other_books") or []

    # Check needs
    if rating is not None and rating < 4.2:
        service_needs.append("Cover redesign")
    if is_picture_illustrated and rating is not None and rating < 4.5:
        service_needs.append("Illustration")
    if (desc and len(desc) < 150) or (rating is not None and rating < 4.0):
        service_needs.append("Editing")
    if desc and len(desc) < 250:
        service_needs.append("Amazon listing optimization")
    if not has_aplus:
        service_needs.append("A+ Content")
    if not amazon_author_url or (bio and len(bio) < 100):
        service_needs.append("Author Page optimization")
    if not website:
        service_needs.append("Website development")
    if video_status in ["no_public_video_found", "unclear"]:
        service_needs.append("Book trailer / animation")
    if other_books and len(other_books) > 0:
        service_needs.append("Series branding")

    # Audience-size signal: a real social presence with a tiny following means
    # the author is active but under-marketed — a strong service-fit signal.
    # Authors with large audiences already have marketing reach; no bonus.
    max_followers = data.get("max_followers")
    has_social_presence = any(_truthy(data, key) for key in ["instagram_url", "tiktok_url", "youtube_url", "facebook_url"])
    if max_followers is not None and has_social_presence and max_followers < 5000:
        service_needs.append("Social media growth")

    # Add 5 points per service need, capped at 25 points
    service_points = min(25, len(service_needs) * 5)
    score += service_points

    # Dynamic Brand Pitch Recommendations based on SOP
    has_bsp = False  # Best Selling Publisher
    has_ia = False   # Infinity Animations
    has_id = False   # Infiniti Digital

    publishing_needs = {"Cover redesign", "Illustration", "Editing", "Amazon listing optimization", "A+ Content", "Author Page optimization"}
    if any(need in service_needs for need in publishing_needs):
        has_bsp = True
    if other_books and len(other_books) > 0:
        if (rating is not None and rating < 4.3) or (desc and len(desc) < 250) or (not has_aplus):
            has_bsp = True

    if any(need in service_needs for need in {"Book trailer / animation", "Illustration"}):
        has_ia = True
    if video_status in ["no_public_video_found", "unclear"]:
        has_ia = True

    if any(need in service_needs for need in {"Website development", "Series branding"}):
        has_id = True
    if not website:
        has_id = True

    if has_ia:
        service_needs.append("Pitch: Infinity Animations")
    if has_id:
        service_needs.append("Pitch: Infiniti Digital")
    if has_bsp:
        service_needs.append("Pitch: Best Selling Publisher")

    # 4. Public Contact Available (Max 20 points)
    contact_points = 0
    if _truthy(data, "public_email"):
        contact_points += 15
    if _truthy(data, "representation_email") or _truthy(data, "publicist_email"):
        contact_points += 12
    if _truthy(data, "public_phone"):
        contact_points += 8
    if _truthy(data, "contact_page_url"):
        contact_points += 8
    if _truthy(data, "canonical_website"):
        contact_points += 6

    # Visual Social Media bonus
    for key in ["instagram_url", "tiktok_url", "youtube_url", "facebook_url", "linkedin_url"]:
        if _truthy(data, key):
            if key in ["instagram_url", "tiktok_url"]:
                contact_points += 3
            else:
                contact_points += 2

    # High-confidence email-to-domain matching
    if _email_matches_domain(data.get("public_email"), data.get("canonical_website")):
        contact_points += 8

    # Cap contact points at 20 points
    score += min(20, contact_points)

    # 5. Recent Activity / Publication Urgency (Max 10 points)
    pub_date = data.get("publication_date")
    score += _publication_recency_points(pub_date)

    # 6. Multiple-book or Upsell Potential (Max 5 points)
    if other_books and len(other_books) > 0:
        score += 5

    # Identity Confidence Adjustments & Penalties
    identity_confidence = float(data.get("identity_confidence") or 0)
    extraction_confidence = float(data.get("extraction_confidence") or 0)

    if _email_matches_domain(data.get("public_email"), data.get("canonical_website")):
        identity_confidence = max(identity_confidence, 0.85)

    if identity_confidence >= 0.8:
        score += 8
    if extraction_confidence >= 0.7:
        score += 4
    if identity_confidence < 0.5:
        score -= 15
    if extraction_confidence < 0.4:
        score -= 20
    if data.get("author_title_mismatch_risk"):
        score -= 25

    # Final score clamping
    score = max(0, min(100, int(score)))

    # Tier mapping based on SOP
    # - Score 80-100: Priority A (Hot Lead)
    # - Score 65-79: Priority B (Warm Lead)
    # - Score 50-64: Priority C (Cold Lead)
    # - Score < 50: Low Priority (Rejected Lead)
    has_any_email = bool(data.get("public_email") or data.get("representation_email") or data.get("publicist_email"))
    if score >= 80 and has_any_email and video_status in {"no_public_video_found", "unclear"}:
        tier = "hot"
    elif score >= 65:
        tier = "warm"
    elif score >= 50:
        tier = "cold"
    else:
        tier = "rejected"

    return score, tier, service_needs


def score_from_lead(lead) -> tuple[int, str]:
    book = lead.book
    author = lead.author_profile

    # Largest observed audience across audited social profiles (None when
    # no profile exposed a follower/subscriber count).
    follower_counts = [
        count
        for count in lead.social_audits.values_list("follower_count", flat=True)
        if count is not None
    ]
    max_followers = max(follower_counts) if follower_counts else None

    score, tier, service_needs = score_lead(
        {
            "is_childrens_book": book.is_childrens_book,
            "is_picture_or_illustrated_book": book.is_picture_or_illustrated_book,
            "category": book.category,
            "amazon_book_url": book.amazon_book_url,
            "asin": book.asin,
            "review_count": book.review_count,
            "rating": book.rating,
            "publisher": book.publisher,
            "publication_date": book.publication_date,
            "has_aplus_content": book.has_aplus_content,
            "other_books": author.other_books if author else [],
            "author_bio": author.author_bio if author else "",
            "amazon_author_url": author.amazon_author_url if author else "",
            # Contact Info
            "public_email": lead.public_email,
            "public_phone": lead.public_phone,
            "representation_email": lead.representation_email,
            "publicist_email": lead.publicist_email,
            "contact_page_url": author.contact_page_url if author else "",
            "canonical_website": author.canonical_website if author else "",
            "instagram_url": author.instagram_url if author else "",
            "facebook_url": author.facebook_url if author else "",
            "tiktok_url": author.tiktok_url if author else "",
            "youtube_url": author.youtube_url if author else "",
            "linkedin_url": author.linkedin_url if author else "",
            "location": lead.location or (author.location if author else ""),
            "publisher_url": author.publisher_url if author else "",
            "video_status": lead.video_status,
            "identity_confidence": author.identity_confidence if author else 0,
            "extraction_confidence": lead.extraction_confidence,
            "max_followers": max_followers,
            "do_not_contact": lead.do_not_contact,
            "manual_review_status": lead.manual_review_status,
        }
    )

    # Save the service needs directly to lead's JSON field safely
    lead.service_needs_json = service_needs
    return score, tier
