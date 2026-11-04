from django import forms

from apps.accounts.validators import validate_graduation_year

from .models import Interest

MIN_INTERESTS = 3


class InterestsForm(forms.Form):
    interests = forms.ModelMultipleChoiceField(
        queryset=Interest.objects.filter(is_active=True), required=False
    )
    major = forms.CharField(max_length=120, required=False)
    graduation_year = forms.IntegerField(required=False, validators=[validate_graduation_year])

    def clean_interests(self):
        interests = self.cleaned_data['interests']
        if len(interests) < MIN_INTERESTS:
            raise forms.ValidationError(f'Pick at least {MIN_INTERESTS} interests, or skip for now.')
        return interests

    def clean_major(self):
        return self.cleaned_data['major'].strip()


class PreferredInterestsForm(forms.Form):
    interests = forms.ModelMultipleChoiceField(
        queryset=Interest.objects.filter(is_active=True), required=False
    )
