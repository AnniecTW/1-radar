from django import forms

from .models import Organization

MAX_LOGO_BYTES = 2 * 1024 * 1024


class OrganizationForm(forms.Form):
    name = forms.CharField(max_length=150)
    org_type = forms.ChoiceField(choices=Organization.OrgType.choices)
    description = forms.CharField(max_length=2000, required=False)
    logo = forms.ImageField(required=False)
    clear_logo = forms.BooleanField(required=False)
    contact_email = forms.EmailField(max_length=254)
    website_url = forms.URLField(max_length=255, required=False)
    instagram_url = forms.URLField(max_length=255, required=False)

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and logo.size > MAX_LOGO_BYTES:
            raise forms.ValidationError('Logo must be 2 MB or smaller.')
        return logo


class VerificationRequestForm(forms.Form):
    note = forms.CharField(max_length=1000, required=False)


class AddMemberForm(forms.Form):
    email = forms.EmailField(max_length=254)
    role = forms.ChoiceField(choices=[
        ('admin', 'Admin'),
        ('checkin_staff', 'Check-in staff'),
    ])


class MemberRoleForm(forms.Form):
    role = forms.ChoiceField(choices=[('admin', 'Admin'), ('checkin_staff', 'Check-in staff')])


class DeleteOrganizationForm(forms.Form):
    confirm_name = forms.CharField(max_length=120)
