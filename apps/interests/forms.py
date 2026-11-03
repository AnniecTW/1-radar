from datetime import date

from django import forms

from .models import Interest

MIN_INTERESTS = 3


class InterestsForm(forms.Form):
    interests = forms.ModelMultipleChoiceField(
        queryset=Interest.objects.filter(is_active=True), required=False
    )
    major = forms.CharField(max_length=120, required=False)
    graduation_year = forms.IntegerField(required=False)

    def clean_interests(self):
        interests = self.cleaned_data['interests']
        if len(interests) < MIN_INTERESTS:
            raise forms.ValidationError(f'Pick at least {MIN_INTERESTS} interests, or skip for now.')
        return interests

    def clean_major(self):
        return self.cleaned_data['major'].strip()

    def clean_graduation_year(self):
        year = self.cleaned_data['graduation_year']
        current_year = date.today().year
        if year is not None and not (current_year - 1 <= year <= current_year + 10):
            raise forms.ValidationError('Enter a valid graduation year.')
        return year
