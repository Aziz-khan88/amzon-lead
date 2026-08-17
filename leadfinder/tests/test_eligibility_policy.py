from leadfinder.models import Book, ContactCandidate, Lead, ResearchRun
from leadfinder.services.eligibility import EligibilityPolicy
from leadfinder.utils.normalize import normalized_book_key


def _lead(*, email="author@example.test"):
    run = ResearchRun.objects.create(keyword="policy", source_provider="manual", status="completed")
    book = Book.objects.create(
        research_run=run,
        title="Policy Book",
        author_name="Policy Author",
        normalized_key=normalized_book_key("Policy Book", "Policy Author", ""),
        source_provider="manual",
    )
    return Lead.objects.create(book=book, public_email=email)


def test_verified_ready_requires_a_verified_candidate_for_the_current_contact(db):
    lead = _lead()
    candidate = ContactCandidate.objects.create(
        lead=lead,
        channel="email",
        role="author",
        raw_value=lead.public_email,
        normalized_value=lead.public_email,
        verification_status="verified",
        verification_score=95,
        deliverability_status="deliverable",
        is_primary=True,
    )
    lead.primary_contact = candidate
    lead.save(update_fields=["primary_contact"])

    decision = EligibilityPolicy.evaluate(lead)

    assert decision.is_verified_ready is True
    assert decision.verified_contact_id == candidate.id
    assert list(EligibilityPolicy.verified_ready(Lead.objects.filter(pk=lead.pk))) == [lead]


def test_verified_ready_rejects_stale_or_legacy_manual_import_candidates(db):
    lead = _lead()
    ContactCandidate.objects.create(
        lead=lead,
        channel="email",
        role="author",
        raw_value="old@example.test",
        normalized_value="old@example.test",
        verification_status="verified",
        verification_score=100,
        deliverability_status="manual_import",
    )

    decision = EligibilityPolicy.evaluate(lead)

    assert decision.is_verified_ready is False
    assert decision.reason_codes == (EligibilityPolicy.REASON_NO_VERIFIED_CONTACT,)
    assert not EligibilityPolicy.verified_ready(Lead.objects.filter(pk=lead.pk)).exists()


def test_do_not_contact_is_never_verified_ready(db):
    lead = _lead()
    ContactCandidate.objects.create(
        lead=lead,
        channel="email",
        role="author",
        raw_value=lead.public_email,
        normalized_value=lead.public_email,
        verification_status="verified",
        verification_score=95,
        deliverability_status="deliverable",
    )
    lead.do_not_contact = True
    lead.save(update_fields=["do_not_contact"])

    decision = EligibilityPolicy.evaluate(lead)

    assert decision.is_verified_ready is False
    assert EligibilityPolicy.REASON_DO_NOT_CONTACT in decision.reason_codes
    assert not EligibilityPolicy.verified_ready(Lead.objects.filter(pk=lead.pk)).exists()
