from leadfinder.services.scoring.lead_score import score_lead


def hot_data():
    return {
        "is_childrens_book": True,
        "is_picture_or_illustrated_book": True,
        "category": "Children's Picture Books",
        "amazon_book_url": "https://www.amazon.com/dp/B012345678",
        "asin": "B012345678",
        "review_count": 12,
        "rating": 4.5,
        "publisher": "Independently published",
        "publication_date": "2025",
        "public_email": "author@example.com",
        "contact_page_url": "https://author.example/contact",
        "canonical_website": "https://author.example",
        "instagram_url": "https://instagram.com/author",
        "location": "Austin, TX",
        "video_status": "no_public_video_found",
        "identity_confidence": 0.9,
        "extraction_confidence": 0.8,
        "manual_review_status": "needs_review",
        "has_aplus_content": False,
    }


def test_hot_lead_with_email_amazon_and_no_public_video():
    score, tier, service_needs = score_lead(hot_data())
    assert score >= 80
    assert tier == "hot"
    assert "A+ Content" in service_needs


def test_found_trailer_gets_penalty():
    base_score, _, _ = score_lead(hot_data())
    data = hot_data()
    data["video_status"] = "found_trailer"
    score, tier, service_needs = score_lead(data)
    assert score < base_score
    assert tier != "hot"
    assert "Book trailer / animation" not in service_needs


def test_do_not_contact_clamps_score_to_zero():
    data = hot_data()
    data["do_not_contact"] = True
    assert score_lead(data) == (0, "rejected", [])


def test_non_children_book_rejected():
    data = hot_data()
    data["is_childrens_book"] = False
    score, tier, service_needs = score_lead(data)
    assert tier == "rejected"
    assert score == 0


def test_traditional_publisher_rejected():
    data = hot_data()
    data["publisher"] = "Scholastic Inc."
    score, tier, service_needs = score_lead(data)
    assert tier == "rejected"
    assert score == 0


def test_missing_contact_reduces_score():
    base_score, _, _ = score_lead(hot_data())
    data = hot_data()
    data["public_email"] = ""
    data["contact_page_url"] = ""
    data["canonical_website"] = ""
    data["instagram_url"] = ""
    score, tier, service_needs = score_lead(data)
    assert score < base_score
    assert tier != "hot"


def test_service_needs_detection():
    data = hot_data()
    data["rating"] = 3.8
    data["description"] = "Too short."
    score, tier, service_needs = score_lead(data)
    
    # Low rating and short description should flag cover, editing, illustration, listing, website, and animation needs
    assert "Cover redesign" in service_needs
    assert "Editing" in service_needs
    assert "Illustration" in service_needs
    assert "Amazon listing optimization" in service_needs
