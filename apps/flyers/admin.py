from django.contrib import admin

from .models import FlyerUpload


@admin.register(FlyerUpload)
class FlyerUploadAdmin(admin.ModelAdmin):
    list_display = ('id', 'uploaded_by', 'status', 'model_name', 'latency_ms', 'created_at')
    list_filter = ('status',)
