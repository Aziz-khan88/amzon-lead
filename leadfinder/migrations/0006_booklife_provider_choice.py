from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leadfinder", "0005_alter_researchrun_source_provider"),
    ]

    operations = [
        migrations.AlterField(
            model_name="researchrun",
            name="source_provider",
            field=models.CharField(
                choices=[
                    ("csv", "CSV"),
                    ("ddgs", "DDGS"),
                    ("tavily", "Tavily"),
                    ("brave", "Brave"),
                    ("google", "Google"),
                    ("amazon_creators", "Amazon Creators"),
                    ("google_books", "Google Books"),
                    ("booklife", "BookLife"),
                    ("manual", "Manual"),
                ],
                default="ddgs",
                max_length=32,
            ),
        ),
    ]
