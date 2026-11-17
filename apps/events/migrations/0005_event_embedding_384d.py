from django.db import migrations
from pgvector.django import VectorField, HnswIndex


def refuse_legacy_vectors(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    table = schema_editor.quote_name(Event._meta.db_table)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM {table} WHERE embedding IS NOT NULL LIMIT 1")
        if cursor.fetchone():
            raise RuntimeError(
                "Event.embedding contains existing vectors. Export/rebuild them through an approved "
                "procedure, clear them explicitly, then rerun this migration; no vectors were changed."
            )


class Migration(migrations.Migration):
    dependencies = [("events", "0004_semantic_embedding")]
    operations = [
        migrations.RunPython(refuse_legacy_vectors, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="event", name="event_embedding_hnsw"),
        migrations.RemoveField(model_name="event", name="semantic_embedding"),
        migrations.RemoveField(model_name="event", name="semantic_embedding_model"),
        migrations.RemoveField(model_name="event", name="semantic_embedding_pooling"),
        migrations.RemoveField(model_name="event", name="semantic_embedding_text_hash"),
        migrations.AlterField(model_name="event", name="embedding",
                              field=VectorField(blank=True, dimensions=384, null=True)),
        migrations.AddIndex(model_name="event", index=HnswIndex(
            name="event_embedding_hnsw", fields=["embedding"], m=16, ef_construction=64,
            opclasses=["vector_cosine_ops"])),
    ]
