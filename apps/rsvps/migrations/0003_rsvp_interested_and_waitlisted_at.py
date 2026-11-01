from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rsvps", "0002_enforce_event_capacity")]

    operations = [
        migrations.AddField(
            model_name="rsvp",
            name="waitlisted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="rsvp",
            name="status",
            field=models.CharField(
                choices=[
                    ("going", "Going"),
                    ("waitlisted", "Waitlisted"),
                    ("interested", "Interested"),
                    ("cancelled", "Cancelled"),
                ],
                max_length=20,
            ),
        ),
    ]
