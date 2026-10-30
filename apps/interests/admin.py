from django.contrib import admin

from .models import Interest, UserInterest


@admin.register(Interest)
class InterestAdmin(admin.ModelAdmin):
    list_display = ('name', 'group', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    exclude = ('embedding',)


@admin.register(UserInterest)
class UserInterestAdmin(admin.ModelAdmin):
    list_display = ('user', 'interest', 'weight', 'source')
    list_filter = ('source',)
