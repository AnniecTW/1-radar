from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("events", "0002_event_checkin_staff_and_contact_fields")]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="slug",
            field=models.SlugField(blank=True, max_length=170, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="event",
            name="title",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterField(
            model_name="event",
            name="start_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="event",
            name="end_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(status="published")
                    | (
                        ~Q(title="")
                        & Q(slug__isnull=False)
                        & ~Q(slug="")
                        & Q(start_at__isnull=False)
                        & Q(end_at__isnull=False)
                        & (Q(venue__isnull=False) | ~Q(location_text=""))
                    )
                ),
                name="published_event_has_required_fields",
            ),
        ),
    ]
