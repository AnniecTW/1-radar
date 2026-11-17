from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("analytics", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="eventdailystats",
            name="interested",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="eventdailystats",
            name="outbound_clicks",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
