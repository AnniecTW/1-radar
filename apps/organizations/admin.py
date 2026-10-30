from django.contrib import admin

from .models import Organization, OrganizationFollow, OrganizationMembership


class MembershipInline(admin.TabularInline):
    model = OrganizationMembership
    fk_name = 'organization'
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'org_type', 'is_verified', 'follower_count', 'created_at')
    list_filter = ('org_type', 'is_verified')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [MembershipInline]


@admin.register(OrganizationFollow)
class OrganizationFollowAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'notify', 'source', 'created_at')
    list_filter = ('notify', 'source')
