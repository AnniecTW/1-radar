from collections import defaultdict

from django.db import migrations, models
from django.db.models.functions import Lower


def normalize_existing_emails(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    alias = schema_editor.connection.alias

    for field in ("email", "campus_email"):
        groups = defaultdict(list)
        for user_id, value in User.objects.using(alias).values_list("id", field):
            if value:
                groups[value.strip().lower()].append(str(user_id))
        duplicates = {value: ids for value, ids in groups.items() if len(ids) > 1}
        if duplicates:
            raise RuntimeError(
                f"Cannot normalize {field}: case-insensitive duplicate accounts exist: {duplicates}"
            )

    for user in User.objects.using(alias).all().only("id", "email", "campus_email").iterator():
        user.email = user.email.strip().lower()
        user.campus_email = user.campus_email.strip().lower() if user.campus_email and user.campus_email.strip() else None
        User.objects.using(alias).filter(pk=user.pk).update(
            email=user.email, campus_email=user.campus_email
        )


EMAIL_NORMALIZATION_SQL = """
CREATE OR REPLACE FUNCTION radar_normalize_user_emails()
RETURNS trigger AS $$
BEGIN
    NEW.email := lower(btrim(NEW.email));
    IF NEW.campus_email IS NOT NULL THEN
        NEW.campus_email := NULLIF(lower(btrim(NEW.campus_email)), '');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER radar_user_email_normalization_insert
BEFORE INSERT ON accounts_user
FOR EACH ROW EXECUTE FUNCTION radar_normalize_user_emails();

CREATE TRIGGER radar_user_email_normalization_update
BEFORE UPDATE OF email, campus_email ON accounts_user
FOR EACH ROW EXECUTE FUNCTION radar_normalize_user_emails();
"""

REVERSE_EMAIL_SQL = """
DROP TRIGGER IF EXISTS radar_user_email_normalization_insert ON accounts_user;
DROP TRIGGER IF EXISTS radar_user_email_normalization_update ON accounts_user;
DROP FUNCTION IF EXISTS radar_normalize_user_emails();
"""


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_lock_supabase_data_api")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(max_length=254),
        ),
        migrations.AlterField(
            model_name="user",
            name="campus_email",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.RunPython(normalize_existing_emails, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(Lower("email"), name="unique_user_email_ci"),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("campus_email"),
                condition=~models.Q(campus_email__isnull=True),
                name="unique_user_campus_email_ci",
            ),
        ),
        migrations.RunSQL(EMAIL_NORMALIZATION_SQL, REVERSE_EMAIL_SQL),
    ]
