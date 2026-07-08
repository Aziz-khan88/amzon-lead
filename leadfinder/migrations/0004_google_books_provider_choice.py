from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leadfinder", "0003_authorprofile_amazon_author_url_and_more"),
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
                    ("amazon_creators", "Amazon Creators"),
                    ("google_books", "Google Books"),
                    ("manual", "Manual"),
                ],
                default="ddgs",
                max_length=32,
            ),
        ),
    ]
