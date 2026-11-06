from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Organization, OrganizationVerificationRequest
from .services import review_verification_request


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


@admin.register(OrganizationVerificationRequest)
class OrganizationVerificationRequestAdmin(admin.ModelAdmin):
    list_display = ('organization', 'status', 'requested_by', 'created_at', 'reviewed_by')
    list_filter = ('status',)
    search_fields = ('organization__name',)
    readonly_fields = ('organization', 'requested_by', 'note', 'status', 'reviewed_by', 'reviewed_at', 'created_at')
    fields = readonly_fields + ('review_note',)
    actions = ['approve_requests', 'reject_requests']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _review(self, request, queryset, approve):
        done = 0
        for verification_request in queryset:
            try:
                review_verification_request(
                    reviewer=request.user, verification_request=verification_request, approve=approve
                )
                done += 1
            except ValidationError as error:
                self.message_user(request, f'{verification_request.organization}: {error.messages[0]}', messages.WARNING)
        self.message_user(request, f'{done} request(s) {"approved" if approve else "rejected"}.')

    @admin.action(description='Approve selected requests (verifies the organizations)')
    def approve_requests(self, request, queryset):
        self._review(request, queryset, True)

    @admin.action(description='Reject selected requests')
    def reject_requests(self, request, queryset):
        self._review(request, queryset, False)
