from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User
from .selectors import is_email_registered


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
