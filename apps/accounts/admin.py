from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.gis.admin import GISModelAdmin

from .models import CampusDomain, Profile, SignInPrompt, User


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ('email', 'username', 'is_email_verified', 'is_campus_verified', 'is_staff', 'date_joined')
    list_filter = ('is_campus_verified', 'is_email_verified', 'is_staff', 'is_active')
    search_fields = ('email', 'username', 'first_name', 'last_name', 'campus_email')
    ordering = ('-date_joined',)
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Radar', {'fields': (
            'is_email_verified', 'is_campus_verified', 'campus_email',
            'onboarding_completed', 'last_active_at',
        )}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (None, {'fields': ('email',)}),
    )


@admin.register(CampusDomain)
class CampusDomainAdmin(GISModelAdmin):
    list_display = ('domain', 'campus_name', 'timezone', 'is_active')


@admin.register(SignInPrompt)
class SignInPromptAdmin(admin.ModelAdmin):
    list_display = ('action', 'target_type', 'outcome', 'action_completed', 'created_at')
    list_filter = ('action', 'outcome')
