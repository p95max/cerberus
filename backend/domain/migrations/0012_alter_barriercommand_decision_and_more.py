from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("domain", "0011_barriercommand_manual_comment_and_more")]

    operations = [
        migrations.AlterField(
            model_name="barriercommand",
            name="decision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="barrier_commands",
                to="domain.accessdecision",
            ),
        ),
        migrations.AddField(
            model_name="barriercommand",
            name="request_reference",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
