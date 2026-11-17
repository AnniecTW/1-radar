from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('events', '0003_draft_optional_publish_requirements')]
    operations = [
        migrations.AddField('event', 'semantic_embedding', models.JSONField(blank=True, editable=False, null=True)),
        migrations.AddField('event', 'semantic_embedding_model', models.CharField(blank=True, editable=False, max_length=100)),
        migrations.AddField('event', 'semantic_embedding_pooling', models.CharField(blank=True, editable=False, max_length=20)),
        migrations.AddField('event', 'semantic_embedding_text_hash', models.CharField(blank=True, editable=False, max_length=64)),
    ]
