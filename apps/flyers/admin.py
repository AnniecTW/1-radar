from django.contrib import admin

from .models import FlyerUpload


@admin.register(FlyerUpload)
class FlyerUploadAdmin(admin.ModelAdmin):
    list_display = ('id', 'uploaded_by', 'status', 'latency_ms', 'fields_edited_count', 'event', 'created_at')
    list_filter = ('status', 'model_name')
    readonly_fields = (
        'uploaded_by', 'organization', 'image', 'status', 'extracted_data', 'confidence', 'raw_response',
        'model_name', 'error_message', 'latency_ms', 'event', 'fields_edited_count', 'processed_at',
        'created_at', 'updated_at',
    )
