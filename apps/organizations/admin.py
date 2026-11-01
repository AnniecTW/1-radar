from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'org_type', 'is_verified', 'follower_count', 'created_at')
    list_filter = ('org_type', 'is_verified')
    search_fields = ('name', 'slug')
    readonly_fields = (
        'name', 'slug', 'org_type', 'description', 'logo', 'contact_email', 'website_url',
        'instagram_url', 'follower_count', 'created_by', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
