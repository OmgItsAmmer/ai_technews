from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Source",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("homepage_url", models.URLField(max_length=500)),
                ("rss_url", models.URLField(blank=True, max_length=500, null=True)),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("official", "Official"),
                            ("media", "Media"),
                            ("blog", "Blog"),
                            ("community", "Community"),
                            ("research", "Research"),
                        ],
                        max_length=20,
                    ),
                ),
                ("badge_label", models.CharField(max_length=50)),
                ("is_active", models.BooleanField(default=True)),
                ("fetch_interval_minutes", models.PositiveIntegerField(default=240)),
                ("last_fetched_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
    ]
