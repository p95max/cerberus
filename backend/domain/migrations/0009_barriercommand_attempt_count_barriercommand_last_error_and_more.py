from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("domain", "0008_barriercontrolsettings")]

    operations = [
        migrations.AddField(
            model_name="barriercommand",
            name="attempt_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="barriercommand",
            name="last_error",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="barriercommand",
            name="retry_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
