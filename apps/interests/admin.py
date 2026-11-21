from django import forms
from django.contrib import admin

from .models import Interest, UserInterest


class InterestAdminForm(forms.ModelForm):
    class Meta:
        model = Interest
        exclude = ('embedding',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Optional in the database so older code can still insert interests, but required here:
        # without it the interest is embedded from its bare name, which gives weak recommendations.
        description = self.fields['description']
        description.required = True
        description.help_text = (
            'Internal only; users never see it. Recommendations compare it with event listings, so write it '
            'like one: the name, a colon, then the kinds of events it covers. Example: "Music: concerts, open mics, '
            'jam sessions, choir and band performances". Only this text is embedded, so saving re-embeds the '
            'interest when it changes. If you rename the interest, update the name at the start of this text too.'
        )


@admin.register(Interest)
class InterestAdmin(admin.ModelAdmin):
    form = InterestAdminForm
    list_display = ('name', 'group', 'description', 'is_active')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(UserInterest)
class UserInterestAdmin(admin.ModelAdmin):
    list_display = ('user', 'interest', 'weight', 'source')
    list_filter = ('source',)
