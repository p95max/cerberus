from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("domain", "0010_accessdecision_manual_review_closed_at_and_more")]

    operations = [
        migrations.AddField(
            model_name="barriercommand",
            name="manual_comment",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="barriercommand",
            name="manual_reason",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
