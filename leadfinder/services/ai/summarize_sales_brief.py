from __future__ import annotations

from .groq_client import GroqJSONClient
from .prompts import SALES_WORDING_RULES


DEFAULT_NOT_TO_SAY = (
    "Do not say the author has no video. Do not criticize their marketing. "
    "Do not imply private data access, partnership, urgency, or certainty beyond the evidence."
)


def summarize_sales_brief(payload: dict, use_ai: bool = True) -> dict:
    prompt = (
        "Create a compliant sales-agent lead brief for outreach. Follow these wording rules:\n"
        f"{SALES_WORDING_RULES}\n\n"
        "Your JSON output MUST contain exactly the following keys with these types:\n"
        "- sales_agent_summary: string (brief overview of the author, book, and outreach strategy)\n"
        "- fit_reason: string (why this author is an ideal fit, e.g. children's picture book fit)\n"
        "- suggested_pitch_angle: string (the recommended angle/focus for outreach)\n"
        "- suggested_first_line: string (suggested opening line of the outreach message)\n"
        "- what_to_say: string (bulleted list of points to mention during outreach)\n"
        "- what_not_to_say: string (bulleted list of points/topics to avoid entirely)\n"
        "- next_best_action: string (the concrete next step for the sales agent)\n"
        "- confidence_summary: string (brief explanation of evidence confidence)\n"
        "- pitch_direct: string (complete professional email draft targeting the author directly, pitching short-form video ads/TikTok reels to boost book sales)\n"
        "- pitch_agent: string (complete professional email draft targeting the literary agent, pitching cinematic rights promos and author branding prestige)\n"
        "- pitch_publicist: string (complete professional email draft targeting the publisher publicist/booking desk, pitching school visit promo materials and library event media kit assets)"
    )
    ai = GroqJSONClient().complete_json(prompt, payload) if use_ai else None
    if ai:
        return ai
    book = payload.get("book", {})
    author = payload.get("author", {})
    video_status = payload.get("video_status", "not_checked")
    safe_video = (
        "I did not find a public book trailer in the sources I checked."
        if video_status == "no_public_video_found"
        else f"Video status needs review: {video_status}."
    )
    title = book.get("title") or "the book"
    author_name = book.get("author_name") or author.get("author_name") or "the author"
    
    # Determine the primary brand fit dynamically based on metadata gaps
    website = author.get("website") or ""
    video_status = payload.get("video_status") or "not_checked"

    if video_status in ["no_public_video_found", "unclear"]:
        primary_brand = "Infinity Animations"
    elif not website:
        primary_brand = "Infiniti Digital"
    else:
        primary_brand = "Best Selling Publisher"

    # Deterministic fallback outreach pitches based on the selected brand
    if primary_brand == "Infinity Animations":
        pitch_direct = (
            f"Subject: Video promotional concept for your book: {title}\n\n"
            f"Hi {author_name},\n\n"
            f"I recently came across your children's book, {title}, on Amazon. It is a highly visual and charming book that would translate beautifully into short-form animated video clips for Instagram Reels and TikTok.\n\n"
            f"At Infinity Animations, we specialize in high-quality animations and book trailers tailored for children's books. We are currently helping children's book authors increase discovery by turning their illustrations into engaging 15-second animated promos.\n\n"
            f"Have you ever considered using custom animations to reach parents on social media? I would love to share a complimentary storyboard concept showing how we could bring the characters from {title} to life.\n\n"
            f"Best regards,\n"
            f"[Your Name]\n"
            f"Infinity Animations\n\n"
            f"---\n"
            f"If you would prefer not to receive future emails about book promotion concepts, please reply with 'Unsubscribe' and we will respect your request immediately."
        )
        pitch_agent = (
            f"Subject: Rights catalogue visual promos for {title} (Author: {author_name})\n\n"
            f"Dear Agent Team,\n\n"
            f"I hope this email finds you well. I am writing regarding your client, {author_name}, and their beautiful children's book, {title}.\n\n"
            f"At Infinity Animations, we help literary agencies elevate their rights catalogs and pitch presentations by creating cinematic animated book trailers. A highly visual 30-second promo can significantly enhance interest when pitching to international publishers, film/TV scouts, and translation rights buyers.\n\n"
            f"Would you be interested in seeing a quick animated concept we prepared for {title} to see how it might support your current rights representation efforts?\n\n"
            f"Sincerely,\n"
            f"[Your Name]\n"
            f"Infinity Animations\n\n"
            f"---\n"
            f"To opt-out of receiving visual derechos/licensing support proposals, please reply with 'Unsubscribe'."
        )
        pitch_publicist = (
            f"Subject: Media kit & school visit animation assets for {title}\n\n"
            f"Dear Publicity Team,\n\n"
            f"I recently reviewed {author_name}'s children's book, {title}, and wanted to reach out regarding visual promotional assets for upcoming campaigns.\n\n"
            f"At Infinity Animations, we create custom, eye-catching animated assets that publicists use for school assembly bookings, media interview pitches, and library event marketing. Short animated sequences are highly effective at capturing the attention of booking coordinators, educators, and local news desks.\n\n"
            f"If you are currently scheduling author visits or school tours for {author_name}, we would love to share a few animated promotional templates tailored for this book.\n\n"
            f"Warm regards,\n"
            f"[Your Name]\n"
            f"Infinity Animations\n\n"
            f"---\n"
            f"If you do not wish to receive publicity design suggestions, please reply with 'Unsubscribe'."
        )
    elif primary_brand == "Infiniti Digital":
        pitch_direct = (
            f"Subject: Digital presence and website concept for {title}\n\n"
            f"Hi {author_name},\n\n"
            f"I recently read about your children's book, {title}, on Amazon. I really enjoyed the visual concept and story behind it.\n\n"
            f"At Infiniti Digital, we work with authors to build premium, responsive website portfolios and establish a strong online presence. Having a central, search-optimized website makes it much easier for schools, librarians, and parents to find you and discover all of your work in one place.\n\n"
            f"Would you be open to a quick look at a custom, mobile-friendly design draft we sketched for your author brand?\n\n"
            f"Best regards,\n"
            f"[Your Name]\n"
            f"Infiniti Digital\n\n"
            f"---\n"
            f"If you would prefer not to receive future emails about book promotion concepts, please reply with 'Unsubscribe' and we will respect your request immediately."
        )
        pitch_agent = (
            f"Subject: Author branding & online presence support for {author_name}\n\n"
            f"Dear Agent Team,\n\n"
            f"I hope this email finds you well. We recently reviewed your client {author_name}'s publication record, including their book {title}.\n\n"
            f"At Infiniti Digital, we specialize in building professional author websites, media hubs, and SEO-optimized digital portfolios. We partner with literary agents to ensure their authors present a cohesive, high-impact public brand that appeals to major publishing houses and media outlets.\n\n"
            f"Could we share a couple of author platform design examples we've developed to see how we could help strengthen {author_name}'s search visibility?\n\n"
            f"Sincerely,\n"
            f"[Your Name]\n"
            f"Infiniti Digital\n\n"
            f"---\n"
            f"To opt-out of receiving visual derechos/licensing support proposals, please reply with 'Unsubscribe'."
        )
        pitch_publicist = (
            f"Subject: Online media kit & landing page assets for {author_name}\n\n"
            f"Dear Publicity Team,\n\n"
            f"I am writing regarding {author_name}'s children's book, {title}. We recently reviewed the book's online visibility and wanted to share some resources.\n\n"
            f"At Infiniti Digital, we construct modern, highly functional author press kits, interactive media pages, and search-optimized landing pages. These web assets are designed to serve as a high-conversion hub for podcast hosts, bloggers, and event coordinators looking to book your author.\n\n"
            f"Would you like to see a brief prototype of a responsive media landing page we could configure to support your PR and publicity outreach for {author_name}?\n\n"
            f"Warm regards,\n"
            f"[Your Name]\n"
            f"Infiniti Digital\n\n"
            f"---\n"
            f"If you do not wish to receive publicity design suggestions, please reply with 'Unsubscribe'."
        )
    else:
        pitch_direct = (
            f"Subject: Enhancing Amazon visibility for your book: {title}\n\n"
            f"Hi {author_name},\n\n"
            f"I recently came across {title} on Amazon. The storytelling is wonderful, and we see immense potential in increasing its discoverability and sales conversion.\n\n"
            f"At Best Selling Publisher, we specialize in helping independent children's authors optimize their Amazon detail pages. This includes creating vibrant A+ Content layouts, writing keyword-rich descriptions, and styling layouts to capture the interest of buying parents instantly.\n\n"
            f"We would love to share a free audit of your book's Amazon listing along with some simple visual recommendations to help improve your conversion.\n\n"
            f"Best regards,\n"
            f"[Your Name]\n"
            f"Best Selling Publisher\n\n"
            f"---\n"
            f"If you would prefer not to receive future emails about book promotion concepts, please reply with 'Unsubscribe' and we will respect your request immediately."
        )
        pitch_agent = (
            f"Subject: Publication visibility & Amazon optimization for {title} (Author: {author_name})\n\n"
            f"Dear Agent Team,\n\n"
            f"I hope this email finds you well. We are writing regarding your client, {author_name}, and their book, {title}.\n\n"
            f"At Best Selling Publisher, we provide specialized catalog optimization services for agents and publishers. We help independent and hybrid-published authors maximize their retail presence on Amazon through A+ Content design, keyword positioning, and professional cover layout reviews.\n\n"
            f"We would be glad to run a complimentary listing audit for {title} to show how optimized retail placement could support your sales velocity.\n\n"
            f"Sincerely,\n"
            f"[Your Name]\n"
            f"Best Selling Publisher\n\n"
            f"---\n"
            f"To opt-out of receiving visual derechos/licensing support proposals, please reply with 'Unsubscribe'."
        )
        pitch_publicist = (
            f"Subject: Metadata and Amazon retail positioning review for {title}\n\n"
            f"Dear Publicity Team,\n\n"
            f"I recently reviewed {author_name}'s book, {title}, and wanted to connect regarding retail channel optimization.\n\n"
            f"At Best Selling Publisher, we support publishing houses and publicity desks by auditing and optimizing the retail metadata pages for key titles. We design premium A+ Content, adjust description syntax for optimal mobile readability, and refine search keywords to ensure your PR efforts convert into retail sales.\n\n"
            f"We would be happy to provide a brief visual audit of the Amazon detail page for {title} to identify opportunities for increasing conversion.\n\n"
            f"Warm regards,\n"
            f"[Your Name]\n"
            f"Best Selling Publisher\n\n"
            f"---\n"
            f"If you do not wish to receive publicity design suggestions, please reply with 'Unsubscribe'."
        )

    return {
        "sales_agent_summary": f"{author_name} is associated with {title}. Evidence is source-linked and needs manual review. Recommended fit: {primary_brand}.",
        "fit_reason": f"The book appears to fit {primary_brand} brand requirements based on available metadata.",
        "suggested_pitch_angle": f"Consultative, evidence-based outreach offering a free preview/audit for {primary_brand}.",
        "suggested_first_line": f"I found your children's book, {title}, while researching visual books that would benefit from {primary_brand}'s services.",
        "what_to_say": f"{safe_video} Recommended outreach brand is {primary_brand}.",
        "what_not_to_say": DEFAULT_NOT_TO_SAY,
        "next_best_action": f"Manually verify the source links, then use the best public contact path pitching {primary_brand}.",
        "confidence_summary": "Generated by deterministic fallback because Groq is not configured or failed.",
        "pitch_direct": pitch_direct,
        "pitch_agent": pitch_agent,
        "pitch_publicist": pitch_publicist,
    }


def render_brief_markdown(lead, source_links: list[str]) -> str:
    book = lead.book
    author = lead.author_profile
    video_text = (
        "No public video found in searched sources."
        if lead.video_status == "no_public_video_found"
        else lead.get_video_status_display()
    )
    return f"""# Lead Brief

## Quick Summary
{lead.sales_agent_summary}

## Book
- Title: {book.title}
- Author: {book.author_name}
- Amazon URL: {book.amazon_book_url or "Missing"}
- ASIN: {book.asin or "Missing"}
- Category: {book.category or "Missing"}
- Publisher: {book.publisher or "Missing"}

## Why This Lead Matters
{lead.fit_reason}

## Video Opportunity
Status: {video_text}
Evidence: Source-linked video/search evidence is listed in the lead record.
Safe wording: I did not find a public book trailer in the sources I checked.

## Contact Path
- Best contact: {lead.public_email or lead.public_phone or "Missing"}
- Backup contact: {(author.contact_page_url if author else "") or "Missing"}
- Website: {(author.canonical_website if author else "") or "Missing"}
- Social: {(author.instagram_url if author else "") or (author.facebook_url if author else "") or "Missing"}

## Confidence
- Book confidence: {book.book_data_confidence}
- Author identity confidence: {(author.identity_confidence if author else 0)}
- Contact confidence: {lead.extraction_confidence}
- Video confidence: {lead.video_confidence}

## Recommended Pitch Angle
{lead.suggested_pitch_angle}

## Suggested First Line
{lead.suggested_first_line}

## What To Say
- {lead.what_to_say}

## What Not To Say
- {lead.what_not_to_say}

## Source Links
{chr(10).join(f"- {url}" for url in source_links) if source_links else "- Missing"}
"""
