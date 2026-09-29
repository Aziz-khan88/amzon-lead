"""Cross-lead shared contact-channel detection.

When the same normalized email or phone appears on many different leads it is
almost always a shared agency / publicist / publishing-services desk rather
than the author.  Those channels remain usable (agent contacts are a
legitimate route), but the pipeline should know they are shared so:

* outreach does not email the same desk many times per day, and
* one shared address cannot corroborate itself across "independent" leads.
"""

from __future__ import annotations


def count_leads_sharing_contact(channel: str, normalized_value: str, *, exclude_lead_id=None) -> int:
    """How many *other* leads carry this exact normalized contact value."""

    if not normalized_value:
        return 0
    from leadfinder.models import ContactCandidate

    query = ContactCandidate.objects.filter(channel=channel, normalized_value=normalized_value)
    if exclude_lead_id is not None:
        query = query.exclude(lead_id=exclude_lead_id)
    return query.values("lead_id").distinct().count()


def leads_sharing_contact(channel: str, normalized_value: str, *, exclude_lead_id=None, limit: int = 50):
    """Return the leads sharing a contact value, for admin review tooling."""

    if not normalized_value:
        return []
    from leadfinder.models import ContactCandidate, Lead

    query = ContactCandidate.objects.filter(channel=channel, normalized_value=normalized_value)
    if exclude_lead_id is not None:
        query = query.exclude(lead_id=exclude_lead_id)
    lead_ids = query.values_list("lead_id", flat=True).distinct()[:limit]
    return list(Lead.objects.filter(id__in=lead_ids).select_related("book"))
