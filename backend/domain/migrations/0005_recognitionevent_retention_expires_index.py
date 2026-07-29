from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0004_recognitionevent_image_metadata"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="recognitionevent",
            index=models.Index(fields=["retention_expires_at"], name="domain_retent_expires_idx"),
        ),
    ]
