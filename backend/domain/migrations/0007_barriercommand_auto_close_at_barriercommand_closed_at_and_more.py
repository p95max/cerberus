from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0006_recognitionretentionpolicy"),
    ]

    operations = [
        migrations.AddField(
            model_name="barriercommand",
            name="auto_close_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="barriercommand",
            name="closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="barriercommand",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("sent", "Sent"),
                    ("acknowledged", "Acknowledged"),
                    ("failed", "Failed"),
                    ("expired", "Expired"),
                    ("closed", "Closed"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
    ]
