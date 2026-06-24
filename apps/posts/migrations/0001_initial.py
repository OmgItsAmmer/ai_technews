import django.contrib.postgres.indexes
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("sources", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Post",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=500)),
                ("original_url", models.URLField(blank=True, max_length=1000, null=True, unique=True)),
                ("author", models.CharField(blank=True, max_length=200, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("fetched_at", models.DateTimeField(auto_now_add=True)),
                ("raw_content", models.TextField(blank=True, default="")),
                ("summary", models.TextField(blank=True, default="")),
                ("tags", models.JSONField(blank=True, default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("url_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="posts",
                        to="sources.source",
                    ),
                ),
            ],
            options={
                "ordering": ["-published_at", "-fetched_at"],
            },
        ),
        migrations.AddIndex(
            model_name="post",
            index=models.Index(fields=["status", "published_at"], name="posts_post_status_8de7d2_idx"),
        ),
        migrations.AddIndex(
            model_name="post",
            index=django.contrib.postgres.indexes.GinIndex(fields=["tags"], name="posts_tags_gin"),
        ),
    ]
