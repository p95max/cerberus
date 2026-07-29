from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("domain", "0009_barriercommand_attempt_count_barriercommand_last_error_and_more")]

    operations = [
        migrations.AddField(
            model_name="accessdecision",
            name="manual_review_closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="accessdecision",
            name="manual_review_closed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="closed_manual_review_cases",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
