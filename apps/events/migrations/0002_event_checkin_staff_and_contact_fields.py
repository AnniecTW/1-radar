import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="contact_info",
            field=models.CharField(blank=True, max_length=254, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="cancel_reason",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="EventCheckInStaff",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "assigned_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checkin_staff_assignments_made",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checkin_staff_assignments",
                        to="events.event",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checkin_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event", "user"), name="unique_event_checkin_staff"
                    )
                ]
            },
        ),
    ]
