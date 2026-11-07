from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User
from apps.interests.forms import PreferredInterestsForm

from .selectors import NOTIFICATION_UPDATES, is_email_registered
from .validators import validate_graduation_year


class LoginForm(forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(strip=False)
    remember = forms.BooleanField(required=False)


class SignupForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(max_length=254)
    password1 = forms.CharField(strip=False)
    password2 = forms.CharField(strip=False)
    terms = forms.BooleanField(error_messages={'required': 'You must agree to the Terms and Privacy Policy.'})

    def clean_email(self) -> str:
        email = self.cleaned_data['email'].strip().lower()
        if is_email_registered(email):
            raise ValidationError('An account with this email already exists.')
        return email

    def clean(self) -> dict:
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        if not password1:
            return cleaned_data
        if password1 != cleaned_data.get('password2'):
            self.add_error('password2', 'Passwords do not match.')
            return cleaned_data
        # An unsaved user lets the similarity validator compare the password to name and email.
        candidate = User(
            email=cleaned_data.get('email', ''),
            first_name=cleaned_data.get('first_name', ''),
            last_name=cleaned_data.get('last_name', ''),
        )
        try:
            validate_password(password1, user=candidate)
        except ValidationError as error:
            self.add_error('password1', error)
        return cleaned_data


class ProfileForm(forms.Form):
    display_name = forms.CharField(max_length=80)
    bio = forms.CharField(max_length=500, required=False)
    major = forms.CharField(max_length=120, required=False)
    graduation_year = forms.IntegerField(required=False, validators=[validate_graduation_year])


class FeedPreferencesForm(PreferredInterestsForm):
    default_tab = forms.ChoiceField(choices=[('for_you', 'For You'), ('following', 'Following')])
    free_only = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, _ in NOTIFICATION_UPDATES:
            self.fields[f'{key}_app'] = forms.BooleanField(required=False)
            self.fields[f'{key}_email'] = forms.BooleanField(required=False)


class LocationPreferencesForm(forms.Form):
    use = forms.ChoiceField(choices=[('session', 'Session'), ('save', 'Save'), ('off', 'Off')])
    start_with_walk = forms.BooleanField(required=False)
    show_heat_map = forms.BooleanField(required=False)
    default_map_view = forms.ChoiceField(choices=[('map', 'Map'), ('satellite', 'Satellite'), ('list', 'List')])


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(max_length=254)


class ResetPasswordForm(forms.Form):
    password1 = forms.CharField(strip=False)
    password2 = forms.CharField(strip=False)

    def __init__(self, *args, user: User, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self) -> dict:
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        if not password1:
            return cleaned_data
        if password1 != cleaned_data.get('password2'):
            self.add_error('password2', 'Passwords do not match.')
            return cleaned_data
        try:
            validate_password(password1, user=self.user)
        except ValidationError as error:
            self.add_error('password1', error)
        return cleaned_data
