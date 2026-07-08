import logging
from datetime import timedelta
from django.utils import timezone
from django.core.mail import EmailMessage
from leadfinder.models import Lead, EmailSender, OutreachCampaign, CampaignStep, CampaignEnrollment, CampaignActivity

logger = logging.getLogger(__name__)


def compile_template(template_str: str, lead: Lead) -> str:
    """
    Replaces dynamic placeholders in a template string with actual values from a Lead.
    Supported tags:
    - {{author_name}}
    - {{book_title}}
    - {{suggested_first_line}}
    - {{suggested_pitch_angle}}
    - {{video_status}}
    - {{lead_score}}
    """
    if not template_str:
        return ""

    author_name = lead.book.author_name
    if not author_name and lead.author_profile:
        author_name = lead.author_profile.author_name
    author_name = author_name or "there"

    replacements = {
        "{{author_name}}": author_name,
        "{{book_title}}": lead.book.title or "your book",
        "{{suggested_first_line}}": lead.suggested_first_line or "",
        "{{suggested_pitch_angle}}": lead.suggested_pitch_angle or "",
        "{{video_status}}": lead.get_video_status_display() or "",
        "{{lead_score}}": str(lead.lead_score),
    }

    result = template_str
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result


def run_outreach_dispatcher() -> int:
    """
    Finds due campaign enrollments, selects an active sender using round-robin,
    compiles and sends the step email via SMTP, and queues the next sequence step.
    Returns the number of successfully sent emails.
    """
    now = timezone.now()
    # Retrieve all enrollments that are ready for their next step
    enrollments = CampaignEnrollment.objects.filter(
        status__in=["queued", "step1_sent", "step2_sent"],
        next_action_date__lte=now
    ).select_related("campaign", "lead", "lead__book", "lead__author_profile")

    sent_count = 0

    for enrollment in enrollments:
        campaign = enrollment.campaign
        lead = enrollment.lead

        # Determine target recipient email address
        recipient_email = lead.public_email or lead.representation_email or lead.publicist_email
        if not recipient_email:
            logger.warning(f"Skipping lead {lead.id} - no valid email address found.")
            enrollment.status = "completed"
            enrollment.save(update_fields=["status", "updated_at"])
            continue

        # Get steps for this campaign
        steps = campaign.steps.all().order_by("step_number")
        if not steps.exists():
            logger.warning(f"Campaign {campaign.name} has no steps defined. Completing enrollment.")
            enrollment.status = "completed"
            enrollment.save(update_fields=["status", "updated_at"])
            continue

        # Figure out which step to send
        current_status = enrollment.status
        target_step_num = 1
        if current_status == "step1_sent":
            target_step_num = 2
        elif current_status == "step2_sent":
            target_step_num = 3

        # Retrieve target step
        step = steps.filter(step_number=target_step_num).first()
        if not step:
            # No subsequent step exists in this campaign
            logger.info(f"Enrollment for lead {lead.id} completed campaign sequences.")
            enrollment.status = "completed"
            enrollment.save(update_fields=["status", "updated_at"])
            continue

        # Select an active sender using round-robin (sort by last_sent_at or sent_today)
        senders = campaign.senders.filter(is_active=True).order_by("last_sent_at", "sent_today")
        sender = None
        for s in senders:
            if s.has_capacity():
                sender = s
                break

        if not sender:
            logger.warning(f"No active email sender with remaining capacity found for campaign {campaign.name}.")
            # Schedule next attempt in 1 hour so dispatcher doesn't lock
            enrollment.next_action_date = now + timedelta(hours=1)
            enrollment.save(update_fields=["next_action_date", "updated_at"])
            continue

        # Compile email components
        subject = compile_template(step.subject_template, lead)
        body = compile_template(step.body_template, lead)

        try:
            # Safe connection construction using django's get_connection
            from django.conf import settings
            from django.core.mail import get_connection

            backend_class = getattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
            
            # If in unit tests (using locmem/console/dummy backends), let Django handle connection
            if "locmem" in backend_class or "console" in backend_class or "dummy" in backend_class:
                connection = get_connection(backend_class)
            else:
                # In production, dynamically initialize custom SMTP connection with sender credentials
                connection = get_connection(
                    "django.core.mail.backends.smtp.EmailBackend",
                    host=sender.smtp_host,
                    port=sender.smtp_port,
                    username=sender.smtp_username,
                    password=sender.get_smtp_password(),
                    use_tls=True,
                    fail_silently=False
                )

            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=f"{sender.name} <{sender.smtp_username}>",
                to=[recipient_email],
                connection=connection
            )
            email.send()

            # Successfully sent! Record activity log
            CampaignActivity.objects.create(
                enrollment=enrollment,
                activity_type="sent",
                details=f"Step {target_step_num} sent by {sender.smtp_username}"
            )

            # Update sender metrics
            sender.sent_today += 1
            sender.last_sent_at = now
            sender.save(update_fields=["sent_today", "last_sent_at", "updated_at"])

            # Schedule the next sequence step
            next_step_num = target_step_num + 1
            next_step = steps.filter(step_number=next_step_num).first()

            if next_step:
                enrollment.status = f"step{target_step_num}_sent"
                enrollment.next_action_date = now + timedelta(days=next_step.delay_days)
            else:
                enrollment.status = "completed"

            enrollment.assigned_sender = sender
            enrollment.last_activity_at = now
            enrollment.save(update_fields=["status", "next_action_date", "assigned_sender", "last_activity_at", "updated_at"])

            sent_count += 1
            logger.info(f"Outreach step {target_step_num} sent successfully to {recipient_email}")

        except Exception as e:
            logger.error(f"Failed to send outreach step {target_step_num} to {recipient_email}: {e}")
            # Try again in 2 hours on failure to prevent email loop blocks
            enrollment.next_action_date = now + timedelta(hours=2)
            enrollment.save(update_fields=["next_action_date", "updated_at"])

            CampaignActivity.objects.create(
                enrollment=enrollment,
                activity_type="bounce",
                details=f"Failed to send Step {target_step_num}: {str(e)}"
            )

    return sent_count
