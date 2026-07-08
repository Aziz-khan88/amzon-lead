from __future__ import annotations

import uuid
import django.core.signing

from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ResearchRun(TimestampedModel):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("canceled", "Canceled"),
    ]
    PROVIDER_CHOICES = [
        ("csv", "CSV"),
        ("ddgs", "DDGS"),
        ("tavily", "Tavily"),
        ("brave", "Brave"),
        ("google", "Google"),
        ("amazon_creators", "Amazon Creators"),
        ("google_books", "Google Books"),
        ("booklife", "BookLife"),
        ("manual", "Manual"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keyword = models.CharField(max_length=255, blank=True)
    source_provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default="ddgs")
    marketplace = models.CharField(max_length=16, default="US")
    max_books = models.IntegerField(default=25)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    settings_json = models.JSONField(default=dict, blank=True)

    def mark_running(self) -> None:
        self.status = "running"
        self.started_at = timezone.now()
        self.error_message = ""
        self.save(update_fields=["status", "started_at", "error_message", "updated_at"])

    def mark_completed(self) -> None:
        self.status = "completed"
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def mark_failed(self, message: str) -> None:
        self.status = "failed"
        self.error_message = message[:5000]
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    def mark_canceled(self) -> None:
        self.status = "canceled"
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def __str__(self) -> str:
        return f"{self.keyword or self.source_provider} ({self.status})"


class Book(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    research_run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name="books")
    title = models.CharField(max_length=500)
    author_name = models.CharField(max_length=255, blank=True)
    illustrator_name = models.CharField(max_length=255, blank=True)
    asin = models.CharField(max_length=20, blank=True, db_index=True)
    amazon_book_url = models.URLField(max_length=1000, blank=True)
    amazon_source_url = models.URLField(max_length=1000, blank=True)
    amazon_source_title = models.CharField(max_length=500, blank=True)
    amazon_source_snippet = models.TextField(blank=True)
    category = models.CharField(max_length=255, blank=True)
    review_count = models.IntegerField(null=True, blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    publication_date = models.CharField(max_length=100, blank=True)
    cover_image_url = models.URLField(max_length=1000, blank=True)
    normalized_key = models.CharField(max_length=600, db_index=True)
    book_data_confidence = models.FloatField(default=0)
    source_provider = models.CharField(max_length=32)
    source_raw_json = models.JSONField(default=dict, blank=True)
    is_childrens_book = models.BooleanField(null=True, blank=True)
    is_picture_or_illustrated_book = models.BooleanField(null=True, blank=True)
    book_classification_confidence = models.FloatField(default=0)
    book_classification_reason = models.TextField(blank=True)
    has_aplus_content = models.BooleanField(null=True, blank=True)


    def __str__(self) -> str:
        return f"{self.title} by {self.author_name or 'Unknown'}"


class AuthorProfile(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author_name = models.CharField(max_length=255)
    normalized_author_key = models.CharField(max_length=255, db_index=True)
    canonical_website = models.URLField(max_length=1000, blank=True)
    contact_page_url = models.URLField(max_length=1000, blank=True)
    publisher_url = models.URLField(max_length=1000, blank=True)
    instagram_url = models.URLField(max_length=1000, blank=True)
    facebook_url = models.URLField(max_length=1000, blank=True)
    tiktok_url = models.URLField(max_length=1000, blank=True)
    youtube_url = models.URLField(max_length=1000, blank=True)
    linkedin_url = models.URLField(max_length=1000, blank=True)
    goodreads_url = models.URLField(max_length=1000, blank=True)
    amazon_author_url = models.URLField(max_length=1000, blank=True)
    author_bio = models.TextField(blank=True)
    author_image_url = models.URLField(max_length=1000, blank=True)
    other_books = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=255, blank=True)
    agent_name = models.CharField(max_length=255, blank=True)
    representation_email = models.EmailField(blank=True)
    publicist_email = models.EmailField(blank=True)
    identity_confidence = models.FloatField(default=0)
    identity_reason = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.author_name


class Lead(TimestampedModel):
    VIDEO_STATUS_CHOICES = [
        ("not_checked", "Not checked"),
        ("found_trailer", "Found trailer"),
        ("found_animated_video", "Found animated video"),
        ("found_read_aloud_only", "Found read aloud only"),
        ("unclear", "Unclear"),
        ("no_public_video_found", "No public video found"),
    ]
    TIER_CHOICES = [
        ("hot", "Hot"),
        ("warm", "Warm"),
        ("cold", "Cold"),
        ("rejected", "Rejected"),
    ]
    REVIEW_CHOICES = [
        ("needs_review", "Needs review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("do_not_contact", "Do not contact"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="leads")
    author_profile = models.ForeignKey(
        AuthorProfile, on_delete=models.SET_NULL, related_name="leads", null=True, blank=True
    )
    public_email = models.EmailField(blank=True)
    public_phone = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=255, blank=True)
    representation_email = models.EmailField(blank=True)
    publicist_email = models.EmailField(blank=True)
    video_status = models.CharField(max_length=32, choices=VIDEO_STATUS_CHOICES, default="not_checked")
    video_confidence = models.FloatField(default=0)
    lead_score = models.IntegerField(default=0)
    lead_tier = models.CharField(max_length=16, choices=TIER_CHOICES, default="cold")
    fit_reason = models.TextField(blank=True)
    sales_agent_summary = models.TextField(blank=True)
    suggested_pitch_angle = models.TextField(blank=True)
    suggested_first_line = models.TextField(blank=True)
    what_to_say = models.TextField(blank=True)
    what_not_to_say = models.TextField(blank=True)
    next_best_action = models.TextField(blank=True)
    extraction_confidence = models.FloatField(default=0)
    manual_review_status = models.CharField(max_length=32, choices=REVIEW_CHOICES, default="needs_review")
    do_not_contact = models.BooleanField(default=False)
    missing_data_json = models.JSONField(default=list, blank=True)
    warnings_json = models.JSONField(default=list, blank=True)
    service_needs_json = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)


    def __str__(self) -> str:
        return f"{self.book.title} lead ({self.lead_score})"


class Evidence(models.Model):
    EVIDENCE_TYPES = [
        ("amazon_search_result", "Amazon search result"),
        ("official_author_site", "Official author site"),
        ("contact_page", "Contact page"),
        ("publisher_site", "Publisher site"),
        ("social_profile", "Social profile"),
        ("youtube_result", "YouTube result"),
        ("vimeo_result", "Vimeo result"),
        ("web_search_result", "Web search result"),
        ("groq_extraction", "Groq extraction"),
        ("manual", "Manual"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="evidence", null=True, blank=True)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="evidence", null=True, blank=True)
    author_profile = models.ForeignKey(
        AuthorProfile, on_delete=models.CASCADE, related_name="evidence", null=True, blank=True
    )
    evidence_type = models.CharField(max_length=32, choices=EVIDENCE_TYPES)
    field_name = models.CharField(max_length=100)
    field_value = models.TextField()
    source_url = models.URLField(max_length=1000)
    source_title = models.CharField(max_length=500, blank=True)
    source_snippet = models.TextField(blank=True)
    confidence = models.FloatField(default=0)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.field_name}: {self.field_value[:60]}"


class SearchQueryLog(models.Model):
    STATUS_CHOICES = [("success", "Success"), ("failed", "Failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    research_run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name="search_logs")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="search_logs", null=True, blank=True)
    query = models.TextField()
    provider = models.CharField(max_length=32)
    result_count = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="success")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SearchResult(models.Model):
    CLASSIFICATION_CHOICES = [
        ("amazon_book", "Amazon book"),
        ("author_site", "Author site"),
        ("publisher_site", "Publisher site"),
        ("youtube", "YouTube"),
        ("vimeo", "Vimeo"),
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
        ("tiktok", "TikTok"),
        ("linkedin", "LinkedIn"),
        ("goodreads", "Goodreads"),
        ("unrelated", "Unrelated"),
        ("unclear", "Unclear"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    search_query_log = models.ForeignKey(SearchQueryLog, on_delete=models.CASCADE, related_name="results")
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1000)
    snippet = models.TextField(blank=True)
    rank = models.IntegerField()
    provider = models.CharField(max_length=32)
    classification = models.CharField(max_length=32, choices=CLASSIFICATION_CHOICES, default="unclear")
    classification_confidence = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class VideoEvidence(models.Model):
    PROVIDER_CHOICES = [("youtube_api", "YouTube API"), ("web_search", "Web search"), ("manual", "Manual")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="videos")
    video_url = models.URLField(max_length=1000)
    title = models.CharField(max_length=500)
    channel_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    published_at = models.CharField(max_length=100, blank=True)
    source_provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default="web_search")
    matches_book = models.BooleanField(null=True, blank=True)
    matches_author = models.BooleanField(null=True, blank=True)
    is_book_trailer = models.BooleanField(default=False)
    is_animated_video = models.BooleanField(default=False)
    is_read_aloud = models.BooleanField(default=False)
    is_author_interview = models.BooleanField(default=False)
    classification_confidence = models.FloatField(default=0)
    classification_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DoNotContact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(blank=True)
    domain = models.CharField(max_length=255, blank=True)
    author_name = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SalesAgentBrief(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name="brief")
    brief_markdown = models.TextField()
    call_notes = models.TextField(blank=True)
    outreach_angle = models.TextField(blank=True)
    objection_notes = models.TextField(blank=True)
    pitch_direct = models.TextField(blank=True)
    pitch_agent = models.TextField(blank=True)
    pitch_publicist = models.TextField(blank=True)
    source_links_json = models.JSONField(default=list, blank=True)

    def __str__(self) -> str:
        return f"Brief for {self.lead}"


class AgentThought(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    research_run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name="agent_thoughts")
    agent_name = models.CharField(max_length=64)  # Scout, Harvester, Auditor, Copywriter, Coordinator
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"[{self.agent_name}] {self.message[:50]} at {self.created_at}"


class EmailSender(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    smtp_host = models.CharField(max_length=255)
    smtp_port = models.IntegerField(default=587)
    smtp_username = models.CharField(max_length=255)
    smtp_password_encrypted = models.CharField(max_length=1000, blank=True)
    imap_host = models.CharField(max_length=255, blank=True)
    imap_port = models.IntegerField(default=993)
    imap_username = models.CharField(max_length=255, blank=True)
    imap_password_encrypted = models.CharField(max_length=1000, blank=True)
    daily_limit = models.IntegerField(default=50)
    sent_today = models.IntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def has_capacity(self) -> bool:
        return self.is_active and (self.sent_today < self.daily_limit)

    def set_smtp_password(self, raw_password: str) -> None:
        self.smtp_password_encrypted = django.core.signing.dumps(raw_password)

    def get_smtp_password(self) -> str:
        if not self.smtp_password_encrypted:
            return ""
        try:
            return django.core.signing.loads(self.smtp_password_encrypted)
        except Exception:
            return ""

    def set_imap_password(self, raw_password: str) -> None:
        self.imap_password_encrypted = django.core.signing.dumps(raw_password)

    def get_imap_password(self) -> str:
        if not self.imap_password_encrypted:
            return ""
        try:
            return django.core.signing.loads(self.imap_password_encrypted)
        except Exception:
            return ""

    def __str__(self) -> str:
        return f"{self.name} ({self.smtp_username})"


class OutreachCampaign(TimestampedModel):
    STATUS_CHOICES = [("draft", "Draft"), ("active", "Active"), ("paused", "Paused")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="draft")
    senders = models.ManyToManyField(EmailSender, related_name="campaigns", blank=True)

    def __str__(self) -> str:
        return self.name


class CampaignStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(OutreachCampaign, on_delete=models.CASCADE, related_name="steps")
    step_number = models.IntegerField()
    subject_template = models.CharField(max_length=255)
    body_template = models.TextField()
    delay_days = models.IntegerField(default=0)

    class Meta:
        ordering = ["step_number"]
        unique_together = ("campaign", "step_number")

    def __str__(self) -> str:
        return f"{self.campaign.name} Step {self.step_number}"


class CampaignEnrollment(TimestampedModel):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("step1_sent", "Step 1 Sent"),
        ("step2_sent", "Step 2 Sent"),
        ("replied", "Replied"),
        ("bounced", "Bounced"),
        ("paused", "Paused"),
        ("completed", "Completed"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(OutreachCampaign, on_delete=models.CASCADE, related_name="enrollments")
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="enrollments")
    assigned_sender = models.ForeignKey(EmailSender, on_delete=models.SET_NULL, null=True, blank=True, related_name="enrollments")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="queued")
    next_action_date = models.DateTimeField()
    last_activity_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("campaign", "lead")

    def __str__(self) -> str:
        return f"{self.lead} in {self.campaign.name}"


class CampaignActivity(TimestampedModel):
    ACTIVITY_TYPES = [
        ("sent", "Sent"),
        ("open", "Email Opened"),
        ("click", "Link Clicked"),
        ("reply", "Reply Received"),
        ("bounce", "Hard Bounce"),
        ("unsubscribe", "Unsubscribed"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(CampaignEnrollment, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=16, choices=ACTIVITY_TYPES)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.activity_type} for {self.enrollment}"

