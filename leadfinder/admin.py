from __future__ import annotations

from django.contrib import admin

from .models import (
    AuthorProfile,
    Book,
    DoNotContact,
    Evidence,
    Lead,
    ResearchRun,
    ScheduledLeadTask,
    SalesAgentBrief,
    SearchQueryLog,
    SearchResult,
    VideoEvidence,
    ContactCandidate,
    SocialProfileAudit,
    VerificationBatch,
    VerificationCheck,
    UserProfile,
    LeadAssignment,
    LeadAssignmentSchedule,
    LeadAssignmentScheduleRun,
)


class HasEmailFilter(admin.SimpleListFilter):
    title = "has public email"
    parameter_name = "has_email"

    def lookups(self, request, model_admin):
        return [("yes", "Yes"), ("no", "No")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(public_email="")
        if self.value() == "no":
            return queryset.filter(public_email="")
        return queryset


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("book", "verification_status", "verification_score", "primary_contact", "video_status", "do_not_contact")
    list_filter = ("verification_status", "video_status", "do_not_contact", HasEmailFilter)
    search_fields = ("book__title", "book__author_name", "public_email", "author_profile__canonical_website")


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "author_name", "asin", "source_provider", "book_data_confidence")
    search_fields = ("title", "author_name", "asin")
    list_filter = ("source_provider", "is_childrens_book", "is_picture_or_illustrated_book")


@admin.register(ResearchRun)
class ResearchRunAdmin(admin.ModelAdmin):
    list_display = ("keyword", "source_provider", "status", "scheduled_task", "max_books", "created_at")
    list_filter = ("source_provider", "status")
    search_fields = ("keyword",)


@admin.register(ScheduledLeadTask)
class ScheduledLeadTaskAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "frequency",
        "source_provider",
        "target_verified_leads",
        "is_active",
        "execution_status",
        "next_run_at",
    )
    list_filter = ("is_active", "execution_status", "frequency", "source_provider")
    search_fields = ("name", "keyword")


@admin.register(AuthorProfile)
class AuthorProfileAdmin(admin.ModelAdmin):
    list_display = ("author_name", "canonical_website", "identity_confidence")
    search_fields = ("author_name", "canonical_website")


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = ("field_name", "evidence_type", "confidence", "source_url", "created_at")
    list_filter = ("evidence_type", "is_primary")
    search_fields = ("field_name", "field_value", "source_url")


admin.site.register(SearchQueryLog)
admin.site.register(SearchResult)
admin.site.register(VideoEvidence)
admin.site.register(DoNotContact)
admin.site.register(SalesAgentBrief)
admin.site.register(ContactCandidate)
admin.site.register(SocialProfileAudit)
admin.site.register(VerificationBatch)
admin.site.register(VerificationCheck)
admin.site.register(UserProfile)
admin.site.register(LeadAssignment)
admin.site.register(LeadAssignmentSchedule)
admin.site.register(LeadAssignmentScheduleRun)
