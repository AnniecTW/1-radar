from django.db import migrations

# Supabase exposes the public schema through its Data API (PostgREST) as the `anon` and
# `authenticated` roles. Radar only talks to the database through Django, so lock that API out:
# enable RLS with no policies (deny all) and revoke the API roles' privileges, including on
# tables created later. Django connects as the table owner, which bypasses RLS.
LOCK_SQL = """
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
        ('admin', '0003_logentry_add_action_flag_choices'),
        ('analytics', '0001_initial'),
        ('attendance', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('discovery', '0001_initial'),
        ('engagement', '0001_initial'),
        ('events', '0001_initial'),
        ('flyers', '0001_initial'),
        ('interests', '0001_initial'),
        ('notifications', '0001_initial'),
        ('organizations', '0001_initial'),
        ('rsvps', '0001_initial'),
        ('search', '0001_initial'),
        ('sessions', '0001_initial'),
        ('venues', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(LOCK_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
