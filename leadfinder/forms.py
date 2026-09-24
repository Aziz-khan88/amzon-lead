from __future__ import annotations

import os

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from leadfinder.models import LeadAssignment, LeadAssignmentSchedule, ScheduledLeadTask, UserProfile

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
    allowed = {"ddgs", "ddgs_html", "bing_html", "fallback", "tavily", "brave", "google"}
    return selected if selected in allowed else "ddgs"


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
            ("kickstarter", "Kickstarter campaigns"),
            ("goodreads_giveaways", "Goodreads giveaways"),
            ("scbwi", "SCBWI directory"),
            ("amazon_new_releases", "Amazon new releases"),
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


class ScheduledLeadTaskForm(forms.ModelForm):
    WEEKDAY_CHOICES = [
        ("mon", "Monday"),
        ("tue", "Tuesday"),
        ("wed", "Wednesday"),
        ("thu", "Thursday"),
        ("fri", "Friday"),
        ("sat", "Saturday"),
        ("sun", "Sunday"),
    ]
    TARGET_CHOICES = [(25, "25 leads"), (50, "50 leads"), (100, "100 leads"), (200, "200 leads")]

    days_of_week = forms.MultipleChoiceField(
        required=False,
        choices=WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label="Run on",
    )
    target_verified_leads = forms.TypedChoiceField(
        choices=TARGET_CHOICES,
        coerce=int,
        initial=50,
        label="Verified lead target",
    )

    class Meta:
        model = ScheduledLeadTask
        fields = [
            "name",
            "keyword",
            "source_provider",
            "frequency",
            "interval_hours",
            "days_of_week",
            "run_time",
            "target_verified_leads",
            "require_contact",
            "only_new_books",
            "verify_email_mx",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Children Illustration Hunt"}),
            "keyword": forms.TextInput(attrs={"placeholder": "e.g. children book illustration"}),
            "run_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "interval_hours": forms.NumberInput(attrs={"min": 1, "max": 720}),
        }
        labels = {
            "only_new_books": "Only include books not seen before",
            "verify_email_mx": "Verify email domains with DNS MX checks",
            "run_time": "Run time",
            "interval_hours": "Repeat every",
            "source_provider": "Search provider",
            "require_contact": "Contact requirement",
        }

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_keyword(self):
        return self.cleaned_data["keyword"].strip()

    def clean_interval_hours(self):
        value = self.cleaned_data.get("interval_hours") or 24
        if value < 1 or value > 720:
            raise forms.ValidationError("Choose an interval between 1 and 720 hours.")
        return value

    def clean(self):
        cleaned = super().clean()
        frequency = cleaned.get("frequency")
        days = cleaned.get("days_of_week") or []
        if frequency in {"weekly", "specific_days"} and not days:
            self.add_error("days_of_week", "Select at least one day for this schedule.")
        if frequency == "weekly" and len(days) > 1:
            self.add_error("days_of_week", "Weekly schedules run on one day; use specific days for multiple days.")
        cleaned["days_of_week"] = list(days) if frequency in {"weekly", "specific_days"} else []
        return cleaned


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
            ("fallback", "Auto (free fallback chain)"),
            ("ddgs", "DDGS"),
            ("ddgs_html", "DuckDuckGo HTML (free)"),
            ("bing_html", "Bing HTML (free)"),
            ("tavily", "Tavily"),
            ("brave", "Brave"),
            ("google", "Google"),
        ],
        initial=default_web_search_provider,
        help_text="Used after BookLife discovery to find official author sites, public social profiles, contact pages, and video evidence. 'Auto' tries each free engine in turn until one answers.",
    )
    require_public_email = forms.BooleanField(required=False, initial=False, label="Require direct public email")
    include_social_only_leads = forms.BooleanField(required=False, initial=True, label="Save social-only leads")
    run_video_search = forms.BooleanField(required=False, initial=True, label="Check existing videos")
    run_groq_ai_extraction = forms.BooleanField(required=False, initial=True, label="Build AI sales brief")

    def clean_booklife_categories(self):
        categories = self.cleaned_data.get("booklife_categories") or []
        return categories or ["all"]


class CSVImportForm(forms.Form):
    csv_file = forms.FileField(label="CSV or Excel file")
    run_video_search = forms.BooleanField(required=False, initial=False, label="Check existing videos")
    verify_imported_contacts = forms.BooleanField(
        required=False,
        initial=False,
        label="Verify imported email and phone",
        help_text="Runs syntax, trusted-source, phone-format, and email-domain checks after the import.",
    )
    run_groq_ai_extraction = forms.BooleanField(required=False, initial=False, label="Build AI sales brief")

    def clean_csv_file(self):
        file = self.cleaned_data["csv_file"]
        if not file.name.lower().endswith((".csv", ".xlsx", ".xlsm")):
            raise forms.ValidationError("Upload a CSV, XLSX, or XLSM file.")
        if file.size > 25 * 1024 * 1024:
            raise forms.ValidationError("Upload a file smaller than 25 MB.")
        return file


class QueryCheckboxInput(forms.CheckboxInput):
    """Checkbox widget that correctly treats '0', 'false', 'off', and 'null' as False."""

    def value_from_datadict(self, data, files, name):
        val = data.get(name)
        if val in (False, "0", 0, "false", "False", "off", "null", None):
            return False
        return super().value_from_datadict(data, files, name)


class QueryBooleanField(forms.BooleanField):
    """BooleanField that works cleanly with URL query parameters like ?valid_only=0 and ?has_email=1."""

    widget = QueryCheckboxInput


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
            ("-verification_score", "Highest Verification Score"),
            ("verification_score", "Lowest Verification Score"),
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
    valid_only = QueryBooleanField(required=False, initial=False, label="Verified-ready only")
    verification_status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Any verification status"),
            ("verified", "Verified"),
            ("not_verified", "Not verified"),
            ("other", "Other"),
        ],
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
    score_min = forms.IntegerField(required=False, min_value=0, max_value=100)
    score_max = forms.IntegerField(required=False, min_value=0, max_value=100)
    has_email = QueryBooleanField(required=False)
    has_phone = QueryBooleanField(required=False)
    verified_email = QueryBooleanField(required=False, label="Verified email")
    verified_phone = QueryBooleanField(required=False, label="Verified phone")
    has_amazon_url = QueryBooleanField(required=False)
    has_website = QueryBooleanField(required=False)
    do_not_contact = QueryBooleanField(required=False)
    pub_year_start = forms.IntegerField(required=False, label="Publish Start Year")
    pub_year_end = forms.IntegerField(required=False, label="Publish End Year")
    assignment_status = forms.ChoiceField(
        required=False,
        choices=[("", "Any task status"), *LeadAssignment.STATUS_CHOICES],
        label="Task status",
    )
    assigned_to = forms.ModelChoiceField(
        required=False,
        queryset=get_user_model().objects.none(),
        empty_label="Any salesperson",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = get_user_model().objects.filter(
            is_active=True,
            leadfinder_profile__role="sales",
        ).order_by("first_name", "last_name", "username")


class LeadAssignmentUpdateForm(forms.ModelForm):
    class Meta:
        model = LeadAssignment
        fields = ["status", "contact_quality", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Call result, next action, or data issue…"})}


class LeadAssignmentScheduleForm(forms.ModelForm):
    WEEKDAY_CHOICES = [
        ("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"),
        ("thu", "Thursday"), ("fri", "Friday"), ("sat", "Saturday"), ("sun", "Sunday"),
    ]
    days_of_week = forms.MultipleChoiceField(
        choices=WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        initial=["mon", "tue", "wed", "thu", "fri"],
    )

    class Meta:
        model = LeadAssignmentSchedule
        fields = [
            "name", "salesperson", "daily_lead_count", "days_of_week", "run_time",
            "contact_requirement", "verified_only", "minimum_lead_score", "is_active",
        ]
        widgets = {
            "run_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "daily_lead_count": forms.NumberInput(attrs={"min": 1, "max": 500}),
            "minimum_lead_score": forms.NumberInput(attrs={"min": 0, "max": 100}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["salesperson"].queryset = get_user_model().objects.filter(
            is_active=True,
            leadfinder_profile__role="sales",
            leadfinder_profile__is_available_for_assignment=True,
        ).order_by("first_name", "last_name", "username")

    def clean_daily_lead_count(self):
        return min(self.cleaned_data["daily_lead_count"], 500)


class TeamMemberCreateForm(UserCreationForm):
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    email = forms.EmailField(required=True, label="Email address")
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, required=False, label="Last name")
    available_for_assignment = forms.BooleanField(
        required=False,
        initial=True,
        label="Available for daily lead assignment",
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = [
            "username", "first_name", "last_name", "email", "role",
            "available_for_assignment", "password1", "password2",
        ]

    def __init__(self, *args, force_sales_role=False, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "username": "sales-jane",
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane@example.com",
        }
        for name, placeholder in placeholders.items():
            self.fields[name].widget.attrs.setdefault("placeholder", placeholder)
        if force_sales_role:
            self.fields["role"].choices = [("sales", "Salesperson")]
            self.fields["role"].initial = "sales"
            self.fields["role"].widget = forms.HiddenInput()

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data["role"]
        if role == "super_admin":
            user.is_staff = True
            user.is_superuser = True
        if commit:
            user.save()
        if commit:
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "role": role,
                    "is_available_for_assignment": role == "sales" and self.cleaned_data["available_for_assignment"],
                },
            )
        return user



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
