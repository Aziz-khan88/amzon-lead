from __future__ import annotations

import os

from django import forms
from django.conf import settings

from leadfinder.services.booklife import BOOKLIFE_AGE_FILTERS, booklife_category_choices
from leadfinder.services.books.isbn_intelligence import parse_identifier_batch


def default_search_provider() -> str:
    selected = getattr(settings, "SEARCH_PROVIDER", "ddgs")
    if selected == "tavily" and not os.getenv("TAVILY_API_KEY"):
        return "ddgs"
    if selected == "brave" and not os.getenv("BRAVE_API_KEY"):
        return "ddgs"
    if selected == "google" and not (os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID")):
        return "ddgs"
    if selected == "google_books" and not os.getenv("GOOGLE_BOOKS_API_KEY"):
        return "ddgs"
    return selected


def default_web_search_provider() -> str:
    selected = default_search_provider()
    return selected if selected in {"ddgs", "tavily", "brave", "google"} else "ddgs"


class ResearchRunForm(forms.Form):
    keyword = forms.CharField(
        max_length=255,
        required=False,
        label="Search keyword",
        widget=forms.TextInput(attrs={"placeholder": "Enter a keyword or topic to discover leads..."}),
    )
    source_provider = forms.ChoiceField(
        label="Source",
        choices=[
            ("ddgs", "DDGS"),
            ("tavily", "Tavily"),
            ("brave", "Brave"),
            ("google", "Google"),
            ("csv", "CSV"),
            ("amazon_creators", "Amazon Creators"),
            ("google_books", "Google Books"),
            ("booklife", "BookLife"),
        ],
        initial=default_search_provider,
    )
    max_books = forms.IntegerField(
        min_value=1,
        max_value=700,
        initial=min(getattr(settings, "APP_MAX_BOOKS_PER_RUN", 10), 10),
        label="Book limit",
    )
    marketplace = forms.CharField(max_length=16, initial="US", label="Marketplace")
    require_amazon_url = forms.BooleanField(required=False, initial=True, label="Require Amazon URL")
    require_public_email = forms.BooleanField(
        required=False,
        initial=False,
        label="Require direct public email",
        help_text="Leave off for warmer contact-page/agent leads; turn on when you only want direct email rows.",
    )
    include_social_only_leads = forms.BooleanField(required=False, initial=False, label="Save social-only leads")
    run_video_search = forms.BooleanField(required=False, initial=True, label="Check existing videos")
    run_groq_ai_extraction = forms.BooleanField(required=False, initial=True, label="Build AI sales brief")
    location_preference = forms.CharField(
        max_length=255,
        required=False,
        label="Location preference",
        widget=forms.TextInput(attrs={"placeholder": "e.g. United States, UK, Canada"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        provider = cleaned_data.get("source_provider")
        keyword = (cleaned_data.get("keyword") or "").strip()

        if provider not in {"csv", "booklife"} and not keyword:
            self.add_error("keyword", "Enter a keyword for search-based research runs.")
        if provider in {"google_books", "booklife"}:
            cleaned_data["require_amazon_url"] = False

        return cleaned_data


class BookLifeRunForm(forms.Form):
    booklife_categories = forms.MultipleChoiceField(
        required=False,
        choices=booklife_category_choices,
        widget=forms.CheckboxSelectMultiple,
        label="BookLife categories",
    )
    age_filter = forms.ChoiceField(choices=BOOKLIFE_AGE_FILTERS, initial="all", label="Age fit")
    max_books = forms.IntegerField(
        min_value=1,
        max_value=700,
        initial=min(getattr(settings, "APP_MAX_BOOKS_PER_RUN", 10), 25),
        label="Book limit",
    )
    enrichment_provider = forms.ChoiceField(
        label="Enrichment source",
        choices=[
            ("ddgs", "DDGS"),
            ("tavily", "Tavily"),
            ("brave", "Brave"),
            ("google", "Google"),
        ],
        initial=default_web_search_provider,
        help_text="Used after BookLife discovery to find official author sites, public social profiles, contact pages, and video evidence.",
    )
    require_public_email = forms.BooleanField(required=False, initial=False, label="Require direct public email")
    include_social_only_leads = forms.BooleanField(required=False, initial=True, label="Save social-only leads")
    run_video_search = forms.BooleanField(required=False, initial=True, label="Check existing videos")
    run_groq_ai_extraction = forms.BooleanField(required=False, initial=True, label="Build AI sales brief")

    def clean_booklife_categories(self):
        categories = self.cleaned_data.get("booklife_categories") or []
        return categories or ["all"]


class CSVImportForm(forms.Form):
    csv_file = forms.FileField(label="CSV file")
    run_video_search = forms.BooleanField(required=False, initial=True, label="Check existing videos")
    run_groq_ai_extraction = forms.BooleanField(required=False, initial=True, label="Build AI sales brief")

    def clean_csv_file(self):
        file = self.cleaned_data["csv_file"]
        if not file.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a CSV file.")
        return file


class LeadFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search Query",
        widget=forms.TextInput(attrs={"placeholder": "Search title, author or email...", "class": "form-control"}),
    )
    sort_by = forms.ChoiceField(
        required=False,
        label="Order By",
        choices=[
            ("-created_at", "Newest First"),
            ("created_at", "Oldest First"),
            ("-lead_score", "Highest Score First"),
            ("lead_score", "Lowest Score First"),
            ("book__title", "Book Title (A-Z)"),
            ("book__author_name", "Author Name (A-Z)"),
        ],
        initial="-created_at",
    )
    min_confidence = forms.ChoiceField(
        required=False,
        label="Min Confidence",
        choices=[
            ("", "Any confidence"),
            ("0.3", ">= 30%"),
            ("0.5", ">= 50%"),
            ("0.7", ">= 70%"),
            ("0.9", ">= 90%"),
        ],
    )
    valid_only = forms.BooleanField(required=False, initial=False, label="Verified-ready only")
    tier = forms.ChoiceField(
        required=False,
        choices=[("", "Any tier"), ("hot", "Hot"), ("warm", "Warm"), ("cold", "Cold"), ("rejected", "Rejected")],
    )
    video_status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Any video status"),
            ("not_checked", "Not checked"),
            ("found_trailer", "Found trailer"),
            ("found_animated_video", "Found animated video"),
            ("found_read_aloud_only", "Found read aloud only"),
            ("unclear", "Unclear"),
            ("no_public_video_found", "No public video found"),
        ],
    )
    manual_review_status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Any review status"),
            ("needs_review", "Needs review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("do_not_contact", "Do not contact"),
        ],
    )
    score_min = forms.IntegerField(required=False, min_value=0, max_value=100)
    score_max = forms.IntegerField(required=False, min_value=0, max_value=100)
    has_email = forms.BooleanField(required=False)
    has_phone = forms.BooleanField(required=False)
    has_amazon_url = forms.BooleanField(required=False)
    has_website = forms.BooleanField(required=False)
    do_not_contact = forms.BooleanField(required=False)
    pub_year_start = forms.IntegerField(required=False, label="Publish Start Year")
    pub_year_end = forms.IntegerField(required=False, label="Publish End Year")



class ISBNSearchForm(forms.Form):
    isbn = forms.CharField(
        label="ASIN / ISBN List",
        widget=forms.Textarea(attrs={
            "placeholder": "Enter one ASIN or ISBN per line, or separate them with commas.\ne.g.,\nB0DQ1YHSZX\n0316452505\nB0NEWASINX",
            "class": "form-control",
            "rows": 4,
        }),
        help_text="ISBN checksums must agree across three implementations. B0-prefixed ASINs remain unverified until source evidence is found.",
    )
    run_video_search = forms.BooleanField(required=False, initial=True, label="Identify Book Trailers & YouTube Videos")
    run_groq_ai_extraction = forms.BooleanField(required=False, initial=True, label="Use Groq AI for Deep Metadata Parsing")

    def clean_isbn(self):
        analyses, invalid = parse_identifier_batch(self.cleaned_data["isbn"])
        if invalid:
            sample = ", ".join(invalid[:5])
            remainder = f" and {len(invalid) - 5} more" if len(invalid) > 5 else ""
            raise forms.ValidationError(f"Invalid identifier(s): {sample}{remainder}.")
        if not analyses:
            raise forms.ValidationError("Enter at least one valid ISBN, ASIN, or Amazon book URL.")
        if len(analyses) > 250:
            raise forms.ValidationError("Process at most 250 unique identifiers in one run.")
        self.identifier_analyses = analyses
        return "\n".join(item.canonical for item in analyses)
