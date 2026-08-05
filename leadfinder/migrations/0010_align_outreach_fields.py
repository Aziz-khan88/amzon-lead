from django.db import migrations, models


OUTREACH_FIELDS = (
    ("outreach_pitch_body", models.TextField(blank=True, default="")),
    ("outreach_pitch_subject", models.CharField(blank=True, default="", max_length=255)),
    ("outreach_status", models.CharField(blank=True, default="not_started", max_length=32)),
)


def add_missing_outreach_columns(apps, schema_editor):
    """Repair databases where these columns were added outside migration history."""
    lead = apps.get_model("leadfinder", "Lead")
    with schema_editor.connection.cursor() as cursor:
        existing = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(cursor, lead._meta.db_table)
        }
    for name, field in OUTREACH_FIELDS:
        if name in existing:
            continue
        field.set_attributes_from_name(name)
        field.model = lead
        schema_editor.add_field(lead, field)


class Migration(migrations.Migration):
    dependencies = [("leadfinder", "0009_emailsender_campaignenrollment_campaignactivity_and_more")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_missing_outreach_columns, migrations.RunPython.noop)],
            state_operations=[
                migrations.AddField(
                    model_name="lead",
                    name="outreach_pitch_body",
                    field=models.TextField(blank=True, default=""),
                ),
                migrations.AddField(
                    model_name="lead",
                    name="outreach_pitch_subject",
                    field=models.CharField(blank=True, default="", max_length=255),
                ),
                migrations.AddField(
                    model_name="lead",
                    name="outreach_status",
                    field=models.CharField(blank=True, default="not_started", max_length=32),
                ),
            ],
        )
    ]
