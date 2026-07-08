import pytest
from datetime import timedelta
from django.utils import timezone
from django.core import mail
from leadfinder.models import Book, Lead, EmailSender, OutreachCampaign, CampaignStep, CampaignEnrollment, CampaignActivity, ResearchRun
from leadfinder.services.pipeline.outreach import compile_template, run_outreach_dispatcher

@pytest.mark.django_db
def test_sender_password_encryption():
    """
    Verifies that smtp and imap passwords are securely signed/encrypted
    and can only be decrypted back to their original plaintext values.
    """
    sender = EmailSender.objects.create(
        name="Outbound Unit Test Sender",
        smtp_host="smtp.example.com",
        smtp_username="test@example.com"
    )
    raw_pass = "super_secret_smtp_123!"
    sender.set_smtp_password(raw_pass)
    sender.save()

    # Refresh from database
    sender.refresh_from_db()
    assert sender.smtp_password_encrypted != raw_pass
    assert sender.get_smtp_password() == raw_pass

    # Verify IMAP password signing as well
    raw_imap = "imap_pass_xyz"
    sender.set_imap_password(raw_imap)
    sender.save()
    sender.refresh_from_db()
    assert sender.imap_password_encrypted != raw_imap
    assert sender.get_imap_password() == raw_imap

    # Test tampering returns empty string
    sender.smtp_password_encrypted = "invalid_encrypted_data_blob"
    assert sender.get_smtp_password() == ""


@pytest.mark.django_db
def test_template_variable_substitution():
    """
    Ensures the template compiler correctly replaces all custom placeholders
    using data on the Book, Lead, and AuthorProfile models.
    """
    run = ResearchRun.objects.create(
        keyword="nature",
        source_provider="manual",
        status="completed"
    )
    book = Book.objects.create(
        research_run=run,
        title="The Whispering Pines",
        author_name="Audrey Woods",
        normalized_key="whispering_pines",
        source_provider="manual"
    )
    lead = Lead.objects.create(
        book=book,
        public_email="audrey@example.com",
        suggested_first_line="I was captivated by the illustrations in The Whispering Pines!",
        suggested_pitch_angle="Let's transform your woodland creatures into a 3D animated trailer.",
        video_status="no_public_video_found",
        lead_score=95
    )

    template = (
        "Hello {{author_name}},\n"
        "Congratulations on publishing '{{book_title}}'.\n"
        "{{suggested_first_line}} {{suggested_pitch_angle}}\n"
        "Since your video status is '{{video_status}}', we scored your book fit at {{lead_score}}%."
    )

    compiled = compile_template(template, lead)

    assert "Hello Audrey Woods" in compiled
    assert "publishing 'The Whispering Pines'" in compiled
    assert "I was captivated by the illustrations in The Whispering Pines!" in compiled
    assert "Let's transform your woodland creatures" in compiled
    assert "video status is 'No public video found'" in compiled
    assert "scored your book fit at 95%" in compiled


@pytest.mark.django_db
def test_outreach_sequence_and_scheduler():
    """
    Tests a full multi-step cold email campaign flow:
    - Step 1 sent -> enrollment transitions to step1_sent and schedules Step 2 delay
    - Step 2 sent -> enrollment transitions to completed
    """
    sender = EmailSender.objects.create(
        name="SMTP Sender",
        smtp_host="smtp.example.com",
        smtp_username="sender@example.com"
    )
    sender.set_smtp_password("testpass")
    sender.save()

    campaign = OutreachCampaign.objects.create(
        name="Picture Book Trailer Outreach",
        status="active"
    )
    campaign.senders.add(sender)

    # Define steps
    step1 = CampaignStep.objects.create(
        campaign=campaign,
        step_number=1,
        subject_template="Quick query regarding {{book_title}}",
        body_template="Hi {{author_name}}, {{suggested_first_line}}",
        delay_days=0
    )
    step2 = CampaignStep.objects.create(
        campaign=campaign,
        step_number=2,
        subject_template="Checking in on {{book_title}}",
        body_template="Hey {{author_name}}, just following up on our animation options.",
        delay_days=3
    )

    run = ResearchRun.objects.create(
        keyword="bunny",
        source_provider="manual",
        status="completed"
    )
    book = Book.objects.create(
        research_run=run,
        title="Bedtime Bunny",
        author_name="Marcus Hare",
        normalized_key="bedtime_bunny",
        source_provider="manual"
    )
    lead = Lead.objects.create(
        book=book,
        public_email="marcus@example.com",
        suggested_first_line="Your bunny illustration is so adorable!",
        lead_score=85
    )

    # Enroll lead in campaign
    enrollment = CampaignEnrollment.objects.create(
        campaign=campaign,
        lead=lead,
        status="queued",
        next_action_date=timezone.now() - timedelta(minutes=5)
    )

    # First dispatch run -> Should send Step 1
    mail.outbox.clear()
    sent_count = run_outreach_dispatcher()

    assert sent_count == 1
    assert len(mail.outbox) == 1
    sent_mail = mail.outbox[0]
    assert sent_mail.to == ["marcus@example.com"]
    assert "Quick query regarding Bedtime Bunny" in sent_mail.subject
    assert "Hi Marcus Hare, Your bunny illustration is so adorable!" in sent_mail.body

    # Check database status updates
    enrollment.refresh_from_db()
    assert enrollment.status == "step1_sent"
    # Delay was 3 days, so next action date should be scheduled 3 days from now
    assert enrollment.next_action_date > timezone.now() + timedelta(days=2)
    assert CampaignActivity.objects.filter(enrollment=enrollment, activity_type="sent").count() == 1

    # Fast forward time to schedule Step 2 dispatch
    enrollment.next_action_date = timezone.now() - timedelta(minutes=5)
    enrollment.save()

    # Second dispatch run -> Should send Step 2
    mail.outbox.clear()
    sent_count = run_outreach_dispatcher()

    assert sent_count == 1
    assert len(mail.outbox) == 1
    sent_mail = mail.outbox[0]
    assert "Checking in on Bedtime Bunny" in sent_mail.subject
    assert "just following up on our animation options" in sent_mail.body

    # Should mark as completed
    enrollment.refresh_from_db()
    assert enrollment.status == "completed"
    assert CampaignActivity.objects.filter(enrollment=enrollment, activity_type="sent").count() == 2


@pytest.mark.django_db
def test_round_robin_inbox_rotation_and_limits():
    """
    Tests that email dispatches are rotated across active inboxes
    using a round-robin format, and senders are bypassed once their daily limits are hit.
    """
    # Create two senders
    sender1 = EmailSender.objects.create(
        name="Sender A",
        smtp_host="smtp.a.com",
        smtp_username="a@example.com",
        daily_limit=1,
        sent_today=0
    )
    sender1.set_smtp_password("apass")
    sender1.save()

    sender2 = EmailSender.objects.create(
        name="Sender B",
        smtp_host="smtp.b.com",
        smtp_username="b@example.com",
        daily_limit=10,
        sent_today=0
    )
    sender2.set_smtp_password("bpass")
    sender2.save()

    campaign = OutreachCampaign.objects.create(
        name="Rotation Test Campaign",
        status="active"
    )
    campaign.senders.add(sender1, sender2)

    step1 = CampaignStep.objects.create(
        campaign=campaign,
        step_number=1,
        subject_template="Book Pitch",
        body_template="Hi {{author_name}}",
        delay_days=0
    )

    run = ResearchRun.objects.create(
        keyword="rotation",
        source_provider="manual",
        status="completed"
    )

    # Create 3 leads
    leads = []
    for idx in range(3):
        b = Book.objects.create(
            research_run=run,
            title=f"Rotation Book {idx}",
            author_name=f"Author {idx}",
            normalized_key=f"rot_book_{idx}",
            source_provider="manual"
        )
        l = Lead.objects.create(
            book=b,
            public_email=f"author{idx}@example.com"
        )
        leads.append(l)

    # Enroll leads one-by-one to test step-by-step rotation
    mail.outbox.clear()

    # First dispatch: Enroll Lead 0
    enr0 = CampaignEnrollment.objects.create(
        campaign=campaign,
        lead=leads[0],
        status="queued",
        next_action_date=timezone.now() - timedelta(minutes=5)
    )
    run_outreach_dispatcher()
    
    sender1.refresh_from_db()
    sender2.refresh_from_db()
    
    # Check that one sender got exactly 1 email sent today
    sent_senders = []
    if sender1.sent_today == 1:
        sent_senders.append(sender1)
    if sender2.sent_today == 1:
        sent_senders.append(sender2)
    assert len(sent_senders) == 1
    first_sender = sent_senders[0]

    # Second dispatch: Enroll Lead 1. It should pick the other sender because it has not sent yet (last_sent_at is older/None)
    enr1 = CampaignEnrollment.objects.create(
        campaign=campaign,
        lead=leads[1],
        status="queued",
        next_action_date=timezone.now() - timedelta(minutes=5)
    )
    run_outreach_dispatcher()
    sender1.refresh_from_db()
    sender2.refresh_from_db()
    assert sender1.sent_today == 1
    assert sender2.sent_today == 1

    # At this point, Sender A (sender1) has hit its daily limit of 1.
    # Third dispatch: Enroll Lead 2. The dispatcher must bypass Sender A and assign the message to Sender B.
    enr2 = CampaignEnrollment.objects.create(
        campaign=campaign,
        lead=leads[2],
        status="queued",
        next_action_date=timezone.now() - timedelta(minutes=5)
    )
    run_outreach_dispatcher()
    sender1.refresh_from_db()
    sender2.refresh_from_db()
    
    # Sender A remains capped at 1, while Sender B goes to 2
    assert sender1.sent_today == 1
    assert sender2.sent_today == 2
    assert len(mail.outbox) == 3

