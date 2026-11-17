from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="type",
            field=models.CharField(
                choices=[
                    ("rsvp_confirmed", "RSVP confirmed"),
                    ("waitlist_joined", "Waitlist Joined"),
                    ("waitlist_promoted", "Waitlist Promoted"),
                    ("waitlist_heads_up", "Waitlist Heads Up"),
                    ("waitlist_closed", "Waitlist Closed"),
                    ("event_updated", "Event Updated"),
                    ("event_cancelled", "Event Cancelled"),
                    ("reminder", "Reminder"),
                    ("org_invite", "Org Invite"),
                    ("followed_org_new_event", "Followed Org New Event"),
                ],
                max_length=40,
            ),
        )
    ]
