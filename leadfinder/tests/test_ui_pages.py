import pytest
from django.urls import reverse

from leadfinder.forms import ResearchRunForm
from leadfinder.models import AuthorProfile, Book, ContactCandidate, Evidence, Lead, ResearchRun, SalesAgentBrief, SearchQueryLog, SearchResult
from leadfinder.services.pipeline.run_research import discovery_queries
from leadfinder.utils.normalize import normalized_book_key


@pytest.fixture
def sample_lead(db):
    run = ResearchRun.objects.create(keyword="picture book", source_provider="csv", status="completed")
    book = Book.objects.create(
        research_run=run,
        title="The Moonlit Bunny Adventure",
        author_name="Avery Moon",
        asin="B012345678",
        amazon_book_url="https://www.amazon.com/dp/B012345678",
        amazon_source_url="uploaded_csv/manual",
        normalized_key=normalized_book_key("The Moonlit Bunny Adventure", "Avery Moon", "B012345678"),
        source_provider="csv",
    )
    author = AuthorProfile.objects.create(
        author_name="Avery Moon",
        normalized_author_key="avery moon",
        canonical_website="https://avery.example",
        contact_page_url="https://avery.example/contact",
        identity_confidence=0.9,
    )
    lead = Lead.objects.create(
        book=book,
        author_profile=author,
        public_email="hello@avery.example",
        video_status="no_public_video_found",
        lead_score=86,
        lead_tier="hot",
    )
    Evidence.objects.create(
        lead=lead,
        field_name="public_email",
        field_value="hello@avery.example",
        evidence_type="contact_page",
        source_url="https://avery.example/contact",
        confidence=0.9,
    )
    query_log = SearchQueryLog.objects.create(
        research_run=run,
        query='site:amazon.com/dp "picture book"',
        provider="ddgs",
        result_count=1,
    )
    SearchResult.objects.create(
        search_query_log=query_log,
        title="The Moonlit Bunny Adventure",
        url="https://www.amazon.com/dp/B012345678",
        rank=1,
        provider="ddgs",
        classification="amazon_book",
        classification_confidence=0.9,
    )
    return lead


def test_research_run_form_requires_keyword_for_search_provider():
    form = ResearchRunForm(data={"source_provider": "ddgs", "max_books": 10, "marketplace": "US"})
    assert not form.is_valid()
    assert "keyword" in form.errors


def test_research_run_form_allows_amazon_creators_provider():
    form = ResearchRunForm(
        data={
            "keyword": "children picture book",
            "source_provider": "amazon_creators",
            "max_books": 10,
            "marketplace": "US",
        }
    )
    assert form.is_valid()


def test_research_run_form_allows_booklife_without_keyword():
    form = ResearchRunForm(
        data={
            "source_provider": "booklife",
            "max_books": 10,
            "marketplace": "US",
        }
    )

    assert form.is_valid()
    assert form.cleaned_data["require_amazon_url"] is False


def test_new_run_starts_background_pipeline_and_redirects(client, db, monkeypatch):
    started = []

    def fake_start(run_id):
        started.append(run_id)

    monkeypatch.setattr("leadfinder.views._start_research_pipeline", fake_start)
    response = client.post(
        reverse("leadfinder:run_new"),
        {
            "keyword": "children picture book test",
            "source_provider": "ddgs",
            "max_books": 1,
            "marketplace": "US",
        },
    )

    run = ResearchRun.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("leadfinder:run_detail", args=[run.id])
    assert started == [run.id]


def test_booklife_run_page_lists_categories(client, db):
    response = client.get(reverse("leadfinder:booklife_run"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "BookLife Run" in html
    assert "Mystery/Thriller" in html
    assert "Children / Young Adult" in html
    assert "BookLife browse pages contain the usable rows" in html


def test_booklife_run_post_starts_background_pipeline(client, db, monkeypatch):
    started = []

    def fake_start(run_id):
        started.append(run_id)

    monkeypatch.setattr("leadfinder.views._start_research_pipeline", fake_start)

    response = client.post(
        reverse("leadfinder:booklife_run"),
        {
            "booklife_categories": ["fiction-romance"],
            "age_filter": "children-young-adult",
            "max_books": 2,
            "enrichment_provider": "ddgs",
            "include_social_only_leads": "on",
        },
    )

    run = ResearchRun.objects.get(source_provider="booklife")
    assert response.status_code == 302
    assert response.url == reverse("leadfinder:run_detail", args=[run.id])
    assert run.settings_json["booklife_categories"] == ["fiction-romance"]
    assert run.settings_json["booklife_age_filter"] == "children-young-adult"
    assert run.settings_json["require_amazon_url"] is False
    assert started == [run.id]


def test_stop_run_marks_pending_run_canceled(client, db):
    run = ResearchRun.objects.create(keyword="children picture book", source_provider="ddgs", status="pending")

    response = client.post(reverse("leadfinder:run_stop", args=[run.id]))

    assert response.status_code == 302
    run.refresh_from_db()
    assert run.status == "canceled"
    assert run.completed_at is not None


def test_retry_run_creates_new_background_run(client, db, monkeypatch):
    started = []

    def fake_start(run_id):
        started.append(run_id)

    monkeypatch.setattr("leadfinder.views._start_research_pipeline", fake_start)
    old_run = ResearchRun.objects.create(
        keyword="Children books illustration",
        source_provider="ddgs",
        status="canceled",
        max_books=10,
        settings_json={"run_video_search": False},
    )

    response = client.post(reverse("leadfinder:run_retry", args=[old_run.id]))

    new_run = ResearchRun.objects.exclude(id=old_run.id).get()
    assert response.status_code == 302
    assert response.url == reverse("leadfinder:run_detail", args=[new_run.id])
    assert new_run.keyword == old_run.keyword
    assert new_run.source_provider == "ddgs"
    assert new_run.settings_json["run_video_search"] is False
    assert started == [new_run.id]


def test_lead_list_defaults_to_all_leads(client, sample_lead):
    rejected_book = Book.objects.create(
        research_run=sample_lead.book.research_run,
        title="Weak Lead Book",
        author_name="Unknown Author",
        normalized_key=normalized_book_key("Weak Lead Book", "Unknown Author", ""),
        source_provider="csv",
    )
    Lead.objects.create(book=rejected_book, lead_score=0, lead_tier="rejected")

    response = client.get(reverse("leadfinder:lead_list"))
    html = response.content.decode()

    assert "The Moonlit Bunny Adventure" in html
    assert "Weak Lead Book" in html


def test_lead_list_hides_verification_table_columns(client, sample_lead):
    response = client.get(reverse("leadfinder:lead_list"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "<th>Verification</th>" not in html
    assert "<th>Verification Status</th>" not in html
    assert 'data-label="Verification"' not in html
    assert 'data-label="Verification Status"' not in html


def test_verified_contact_quick_filters_use_candidate_verification(client, sample_lead):
    verified_email = ContactCandidate.objects.create(
        lead=sample_lead,
        channel="email",
        role="author",
        raw_value="hello@avery.example",
        normalized_value="hello@avery.example",
        verification_status="verified",
        verification_score=92,
        is_primary=True,
    )
    sample_lead.primary_contact = verified_email
    sample_lead.save(update_fields=["primary_contact"])

    response = client.get(reverse("leadfinder:lead_list"), {"verified_email": "1"})
    html = response.content.decode()

    assert response.status_code == 200
    assert "The Moonlit Bunny Adventure" in html
    assert "Verified email" in html
    assert "contact-verified-badge" in html

    phone_response = client.get(reverse("leadfinder:lead_list"), {"verified_phone": "1"})
    assert "The Moonlit Bunny Adventure" not in phone_response.content.decode()


def test_run_list_status_filter_is_functional(client, db):
    ResearchRun.objects.create(keyword="Done run", source_provider="ddgs", status="completed")
    ResearchRun.objects.create(keyword="Working run", source_provider="tavily", status="running")

    response = client.get(reverse("leadfinder:run_list"), {"status": "active"})
    html = response.content.decode()

    assert response.status_code == 200
    assert "Working run" in html
    assert "Done run" not in html


def test_run_list_exposes_a_direct_review_action(client, db):
    run = ResearchRun.objects.create(keyword="Ready run", source_provider="ddgs", status="completed")

    response = client.get(reverse("leadfinder:run_list"))
    html = response.content.decode()

    assert response.status_code == 200
    assert f'href="{reverse("leadfinder:run_detail", args=[run.id])}#run-leads"' in html
    assert "Review 0 leads" in html


def test_settings_never_renders_stored_secrets_or_overwrites_them_when_blank(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "private-key-that-must-not-render")
    saved = {}
    monkeypatch.setattr("leadfinder.views.save_env_settings", lambda updates: saved.update(updates))

    response = client.get(reverse("leadfinder:settings_help"))
    assert response.status_code == 200
    assert b"private-key-that-must-not-render" not in response.content

    response = client.post(
        reverse("leadfinder:settings_help"),
        {"SEARCH_PROVIDER": "ddgs", "GROQ_MODEL": "llama-3.3-70b-versatile", "GROQ_API_KEY": ""},
    )

    assert response.status_code == 302
    assert saved["SEARCH_PROVIDER"] == "ddgs"
    assert "GROQ_API_KEY" not in saved



def test_broad_discovery_queries_start_with_non_exact_amazon_searches():
    queries = discovery_queries("Children books")

    assert queries[0] == "amazon.com/dp children picture book by"
    assert 'site:amazon.com "children picture book" "by"' in queries[:4]
    assert 'site:amazon.com/dp "children picture book"' in queries[:4]
    assert "amazon.com/dp kids picture book by" in queries
    assert "amazon.com/dp Children books by" in queries
    assert "Children book" in " ".join(queries)
    assert "children picture book" in " ".join(queries)


def test_empty_search_run_explains_why_no_leads(client, db):
    run = ResearchRun.objects.create(keyword="Children books", source_provider="ddgs", status="completed")
    SearchQueryLog.objects.create(
        research_run=run,
        query='site:amazon.com/dp "Children books"',
        provider="ddgs",
        result_count=0,
    )

    response = client.get(reverse("leadfinder:run_detail", args=[run.id]))
    html = response.content.decode()

    assert response.status_code == 200
    assert "No search results came back" in html
    assert "no books or leads could be created" in html


@pytest.mark.parametrize(
    "url_name",
    [
        "leadfinder:dashboard",
        "leadfinder:lead_list",
        "leadfinder:run_list",
        "leadfinder:run_new",
        "leadfinder:booklife_run",
        "leadfinder:import_csv",
        "leadfinder:settings_help",
    ],
)
def test_core_pages_render(client, sample_lead, url_name):
    response = client.get(reverse(url_name))
    assert response.status_code == 200


def test_detail_pages_render(client, sample_lead):
    run = sample_lead.book.research_run

    run_response = client.get(reverse("leadfinder:run_detail", args=[run.id]))
    assert run_response.status_code == 200
    run_html = run_response.content.decode()
    assert "The Moonlit Bunny Adventure" in run_html
    assert "Search Logs" in run_html
    assert "Lead Checks" in run_html
    assert "Other" in run_html
    assert 'class="run-detail-page"' in run_html
    assert 'class="panel run-meta-panel run-config-disclosure"' in run_html
    assert "Show run configuration" in run_html
    assert 'class="panel run-log-disclosure"' in run_html
    assert 'id="run-search-logs"' in run_html

    lead_response = client.get(reverse("leadfinder:lead_detail", args=[sample_lead.id]))
    assert lead_response.status_code == 200
    lead_html = lead_response.content.decode()
    assert "hello@avery.example" in lead_html
    assert 'class="lead-detail-page"' in lead_html
    assert 'id="lead-contacts"' in lead_html
    assert 'id="lead-portfolio"' in lead_html


def test_lead_list_does_not_label_an_unverified_direct_email_as_verified(client, sample_lead):
    response = client.get(reverse("leadfinder:lead_list"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Verified email" in html
    assert "<strong>0</strong>" in html

    filtered = client.get(reverse("leadfinder:lead_list"), {"verified_email": "1"})
    filtered_html = filtered.content.decode()

    assert filtered.status_code == 200
    assert "The Moonlit Bunny Adventure" not in filtered_html


def test_run_detail_explains_ai_contact_extraction_outcome(client, db):
    run = ResearchRun.objects.create(
        keyword="ISBN Search: B0TESTAI00",
        source_provider="manual",
        status="completed",
        settings_json={
            "run_groq_ai_extraction": True,
            "run_video_search": False,
        },
    )
    book = Book.objects.create(
        research_run=run,
        title="Book for ASIN B0TESTAI00",
        author_name="",
        asin="B0TESTAI00",
        normalized_key=normalized_book_key("Book for ASIN B0TESTAI00", "", "B0TESTAI00"),
        source_provider="manual",
    )
    lead = Lead.objects.create(book=book, verification_status="other")
    SalesAgentBrief.objects.create(
        lead=lead,
        brief_markdown="# Lead Brief",
        outreach_angle="Manual review",
    )

    response = client.get(reverse("leadfinder:run_detail", args=[run.id]))
    html = response.content.decode()

    assert response.status_code == 200
    assert "AI diagnostics" in html
    assert "Groq extraction requested" in html
    assert "0 saved AI contact evidence rows" in html
    assert "No reliable email or phone was extracted" in html
    assert "1 / 1 lead briefs" in html
    assert "Skipped by setting" in html
    assert "1 books missing author" in html


def test_lead_action_delete(client, sample_lead):
    # Verify the lead exists initially
    assert Lead.objects.filter(id=sample_lead.id).exists()
    
    response = client.post(reverse("leadfinder:lead_action", args=[sample_lead.id, "delete"]))
    assert response.status_code == 302
    assert response.url == reverse("leadfinder:lead_list")
    
    # Verify the lead is deleted from database
    assert not Lead.objects.filter(id=sample_lead.id).exists()


def test_lead_activity_note_does_not_change_review_status(client, sample_lead):
    original_status = sample_lead.manual_review_status

    response = client.post(
        reverse("leadfinder:lead_action", args=[sample_lead.id, "add-note"]),
        {"note": "Checked the public catalog evidence."},
    )

    assert response.status_code == 302
    sample_lead.refresh_from_db()
    assert sample_lead.manual_review_status == original_status
    assert "Checked the public catalog evidence." in sample_lead.notes


def test_lead_bulk_action_reject(client, sample_lead):
    # Create another lead to bulk reject
    book2 = Book.objects.create(
        research_run=sample_lead.book.research_run,
        title="Another Book",
        author_name="Another Author",
        normalized_key=normalized_book_key("Another Book", "Another Author", ""),
        source_provider="csv",
    )
    lead2 = Lead.objects.create(
        book=book2,
        public_email="another@example.com",
        video_status="not_checked",
        lead_score=50,
        lead_tier="warm",
        manual_review_status="needs_review",
    )
    
    # Bulk reject both leads
    response = client.post(
        reverse("leadfinder:lead_bulk_action"),
        {
            "lead_ids": [str(sample_lead.id), str(lead2.id)],
            "action": "bulk_reject",
        }
    )
    assert response.status_code == 302
    
    # Refresh from database and assert statuses are updated to rejected
    sample_lead.refresh_from_db()
    lead2.refresh_from_db()
    assert sample_lead.manual_review_status == "rejected"
    assert lead2.manual_review_status == "rejected"


def test_lead_bulk_action_delete(client, sample_lead):
    # Create another lead to bulk delete
    book2 = Book.objects.create(
        research_run=sample_lead.book.research_run,
        title="Delete Me Book",
        author_name="Delete Me Author",
        normalized_key=normalized_book_key("Delete Me Book", "Delete Me Author", ""),
        source_provider="csv",
    )
    lead2 = Lead.objects.create(
        book=book2,
        public_email="deleteme@example.com",
        video_status="not_checked",
        lead_score=10,
        lead_tier="cold",
    )
    
    # Verify both leads exist initially
    assert Lead.objects.filter(id__in=[sample_lead.id, lead2.id]).count() == 2
    
    # Bulk delete both leads
    response = client.post(
        reverse("leadfinder:lead_bulk_action"),
        {
            "lead_ids": [str(sample_lead.id), str(lead2.id)],
            "action": "bulk_delete",
        }
    )
    assert response.status_code == 302
    
    # Assert both leads are deleted from database
    assert not Lead.objects.filter(id__in=[sample_lead.id, lead2.id]).exists()


def test_lead_bulk_action_no_leads_selected(client, sample_lead):
    response = client.post(
        reverse("leadfinder:lead_bulk_action"),
        {
            "lead_ids": [],
            "action": "bulk_reject",
        }
    )
    assert response.status_code == 302
    
    # Assert lead was NOT rejected
    sample_lead.refresh_from_db()
    assert sample_lead.manual_review_status != "rejected"


def test_delete_rejected_leads_action(client, sample_lead):
    # Verify sample_lead is hot and exists
    assert Lead.objects.filter(id=sample_lead.id).exists()
    assert sample_lead.lead_tier == "hot"
    
    # Create an auto-rejected lead
    book_auto = Book.objects.create(
        research_run=sample_lead.book.research_run,
        title="Auto Rejected",
        normalized_key=normalized_book_key("Auto Rejected", "Author A", ""),
        source_provider="csv",
    )
    lead_auto = Lead.objects.create(
        book=book_auto,
        lead_score=0,
        lead_tier="rejected",
    )
    
    # Create a manually rejected lead
    book_manual = Book.objects.create(
        research_run=sample_lead.book.research_run,
        title="Manually Rejected",
        normalized_key=normalized_book_key("Manually Rejected", "Author M", ""),
        source_provider="csv",
    )
    lead_manual = Lead.objects.create(
        book=book_manual,
        lead_score=50,
        lead_tier="warm",
        manual_review_status="rejected",
    )
    
    # Verify we have 3 leads in database
    assert Lead.objects.count() == 3
    
    # Call the dashboard delete rejected action
    response = client.post(reverse("leadfinder:delete_rejected_leads"))
    assert response.status_code == 302
    assert response.url == reverse("leadfinder:dashboard")
    
    # Verify only the sample_lead remains (the 2 rejected ones are deleted)
    assert Lead.objects.count() == 1
    assert Lead.objects.filter(id=sample_lead.id).exists()
    assert not Lead.objects.filter(id__in=[lead_auto.id, lead_manual.id]).exists()


def test_isbn_search_page_loads(client, db):
    response = client.get(reverse("leadfinder:isbn_search"))
    assert response.status_code == 200
    assert b"ASIN / ISBN List" in response.content
    assert b'aria-label="Select all discovered books"' in response.content
    assert b"AbortController" in response.content
    assert b"isbn-search-workspace" in response.content
    assert b"lookup-result-title" in response.content
    assert b"lookup-selection-status" in response.content
    assert b"direct-form-error" in response.content
    assert b"has-active-direct-run" in response.content
    assert b"alert(" not in response.content


def test_base_loads_shared_motion_and_navigation_script(client, db):
    response = client.get(reverse("leadfinder:dashboard"))

    assert response.status_code == 200
    assert b'/static/leadfinder/app.js' in response.content
    assert b"Ctrl K" in response.content


def test_isbn_search_post_redirects_to_existing_lead(client, db, sample_lead):
    # Retrieve existing ASIN
    asin = sample_lead.book.asin
    response = client.post(
        reverse("leadfinder:isbn_search"),
        {
            "isbn": asin,
            "run_video_search": False,
            "run_groq_ai_extraction": False,
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("leadfinder:lead_detail", kwargs={"pk": sample_lead.id})


def test_isbn_search_post_scrapes_and_redirects(client, db, monkeypatch, sample_lead):
    started = []

    def mock_start_pipeline(run_id):
        started.append(run_id)

    monkeypatch.setattr("leadfinder.views._start_research_pipeline", mock_start_pipeline)

    # Search for a new ASIN that doesn't exist
    response = client.post(
        reverse("leadfinder:isbn_search"),
        {
            "isbn": "B0NEWASINX",
            "run_video_search": True,
            "run_groq_ai_extraction": True,
        },
    )

    assert response.status_code == 302
    run = ResearchRun.objects.get(source_provider="manual")
    assert response.url == f"{reverse('leadfinder:isbn_search')}?run_id={run.id}"
    assert started == [run.id]

    # Verify that the Book was pre-created in the database
    book = Book.objects.get(research_run=run)
    assert book.asin == "B0NEWASINX"
    assert book.amazon_book_url == ""
    assert book.amazon_source_url == ""
    assert book.source_raw_json.get("processing_status") == "pending"


def test_isbn_search_status_endpoint(client, db):
    run = ResearchRun.objects.create(
        keyword="ISBN Search: B0NEWASINX",
        source_provider="manual",
        status="running",
        max_books=1,
    )
    book = Book.objects.create(
        research_run=run,
        title="Test Book",
        asin="B0NEWASINX",
        normalized_key="test_key",
        source_provider="manual",
        source_raw_json={"processing_status": "processing"},
    )

    response = client.get(reverse("leadfinder:isbn_search_status", kwargs={"run_id": run.id}))
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == str(run.id)
    assert data["status"] == "running"
    assert data["total"] == 1
    assert data["processing"] == 1
    assert data["percentage"] == 0
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["asin"] == "B0NEWASINX"
    assert data["tasks"][0]["status"] == "processing"
    assert data["tasks"][0]["stage"] == ""


def test_isbn_search_active_run_console_uses_light_ui(client, db):
    run = ResearchRun.objects.create(
        keyword="ISBN Search: B0ACTIVE1",
        source_provider="manual",
        status="running",
        max_books=1,
    )
    Book.objects.create(
        research_run=run,
        title="Active Test Book",
        asin="B0ACTIVE1",
        normalized_key="active_test_book",
        source_provider="manual",
        source_raw_json={"processing_status": "processing"},
    )

    response = client.get(reverse("leadfinder:isbn_search"), {"run_id": run.id})

    assert response.status_code == 200
    assert b"progress-console-panel" in response.content
    assert b"Active Deep Enrichment" in response.content
    assert b"queue-task-card" in response.content
    assert b"task-title-text" in response.content
    assert b"has-active-direct-run" in response.content
    assert b"task.stage" in response.content


def test_lead_list_filtration_and_sorting(client, sample_lead):
    # Set sample_lead's extraction confidence and book publication date
    sample_lead.extraction_confidence = 0.8
    sample_lead.save()
    sample_lead.book.publication_date = "2025-06-25"
    sample_lead.book.save()

    # Create another lead to verify filtering and sorting
    run = sample_lead.book.research_run
    book2 = Book.objects.create(
        research_run=run,
        title="Zebra Quest Adventure",
        author_name="Zachary Zebra",
        asin="B098765432",
        normalized_key=normalized_book_key("Zebra Quest Adventure", "Zachary Zebra", "B098765432"),
        source_provider="csv",
        amazon_book_url="https://www.amazon.com/dp/B098765432",
        publication_date="2026-01-01",
    )
    author2 = AuthorProfile.objects.create(
        author_name="Zachary Zebra",
        normalized_author_key="zachary zebra",
        identity_confidence=0.5,
    )
    lead2 = Lead.objects.create(
        book=book2,
        author_profile=author2,
        public_email="zebra@example.com",
        lead_score=50,
        lead_tier="warm",
        extraction_confidence=0.4,
    )

    # 1. Search filter ('q')

    response = client.get(reverse("leadfinder:lead_list") + "?q=Zebra")
    html = response.content.decode()
    assert "Zebra Quest Adventure" in html
    assert "The Moonlit Bunny Adventure" not in html

    # 2. Confidence filter ('min_confidence')
    response = client.get(reverse("leadfinder:lead_list") + "?min_confidence=0.5")
    html = response.content.decode()
    assert "The Moonlit Bunny Adventure" in html
    assert "Zebra Quest Adventure" not in html

    # 3. Sorting filter ('sort_by')
    # Default is newest first (so Zebra Quest Adventure is first)
    # A-Z Book title: book__title
    response = client.get(reverse("leadfinder:lead_list") + "?sort_by=book__title")
    html = response.content.decode()
    # The Moonlit Bunny Adventure should appear before Zebra Quest Adventure in A-Z order
    assert html.index("The Moonlit Bunny Adventure") < html.index("Zebra Quest Adventure")

    # Lower score first: lead_score
    response = client.get(reverse("leadfinder:lead_list") + "?sort_by=lead_score")
    html = response.content.decode()
    # lead2 has lead_score=50, sample_lead has lead_score=86. Lower score first means Zebra Quest Adventure is before Moonlit Bunny Adventure
    assert html.index("Zebra Quest Adventure") < html.index("The Moonlit Bunny Adventure")

    # 4. Publication year filter ('pub_year_start')
    response = client.get(reverse("leadfinder:lead_list") + "?pub_year_start=2026")
    html = response.content.decode()
    assert "Zebra Quest Adventure" in html
    assert "The Moonlit Bunny Adventure" not in html

    # 5. Publication year filter ('pub_year_end')
    response = client.get(reverse("leadfinder:lead_list") + "?pub_year_end=2025")
    html = response.content.decode()
    assert "The Moonlit Bunny Adventure" in html
    assert "Zebra Quest Adventure" not in html
