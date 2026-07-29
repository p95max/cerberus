from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0007_barriercommand_auto_close_at_barriercommand_closed_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BarrierControlSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "auto_close_seconds",
                    models.PositiveIntegerField(default=10, validators=[MinValueValidator(1)]),
                ),
            ],
        ),
    ]
