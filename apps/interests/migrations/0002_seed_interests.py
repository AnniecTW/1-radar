from django.db import migrations

# (group, [(name, slug)]) - curated taxonomy for onboarding (FR-8).
TAXONOMY = [
    ('Academic', [('Tech', 'tech'), ('Career', 'career'), ('Study', 'study'), ('Science', 'science')]),
    ('Social', [('Cultural', 'cultural'), ('Food', 'food'), ('Gaming', 'gaming'), ('Networking', 'networking')]),
    ('Creative', [('Arts', 'arts'), ('Music', 'music'), ('Film', 'film'), ('Writing', 'writing')]),
    ('Active & Wellness', [('Sports', 'sports'), ('Wellness', 'wellness'), ('Outdoors', 'outdoors'), ('Fitness', 'fitness')]),
    ('Community', [('Volunteering', 'volunteering'), ('Faith', 'faith'), ('Entrepreneurship', 'entrepreneurship'), ('Activism', 'activism')]),
]


def seed_interests(apps, schema_editor):
    Interest = apps.get_model('interests', 'Interest')
    for group, items in TAXONOMY:
        for name, slug in items:
            Interest.objects.get_or_create(slug=slug, defaults={'name': name, 'group': group, 'is_active': True})


class Migration(migrations.Migration):
    dependencies = [('interests', '0001_initial')]
    operations = [migrations.RunPython(seed_interests, migrations.RunPython.noop)]
