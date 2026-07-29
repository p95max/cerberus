from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0005_recognitionevent_retention_expires_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecognitionRetentionPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("image_metadata_enabled", models.BooleanField(default=True)),
                ("image_metadata_retention_days", models.PositiveIntegerField(default=30)),
                ("event_retention_enabled", models.BooleanField(default=True)),
                ("event_retention_days", models.PositiveIntegerField(default=180)),
                ("aggregate_audit_retention_enabled", models.BooleanField(default=True)),
                ("aggregate_audit_retention_days", models.PositiveIntegerField(default=730)),
            ],
        ),
    ]
