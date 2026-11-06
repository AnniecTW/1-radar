import io
import tempfile

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.organizations.services import (
    MAX_OWNED_ORGANIZATIONS, add_organization_member, create_organization, request_organization_verification,
    review_verification_request, transfer_organization_ownership,
)

PASSWORD = 'Strong-Pass-123'
FORM = {
    'name': 'Chess Club', 'org_type': 'rso', 'description': 'We play chess.',
    'contact_email': 'chess@example.edu', 'website_url': 'https://chess.example.edu',
}


def make_user(name, *, campus=True):
    return User.objects.create_user(
        username=name, email=f'{name}@example.edu', password=PASSWORD, is_campus_verified=campus
    )


def png(name='logo.png', size=(8, 8)):
    buffer = io.BytesIO()
    Image.new('RGB', size).save(buffer, 'PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class OrganizationPageTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner')
        self.admin = make_user('admin')
        self.organization = create_organization(creator=self.owner, name='Test Club', org_type='rso')
        add_organization_member(
            actor=self.owner, organization=self.organization, user=self.admin,
            role=OrganizationMembership.Role.ADMIN,
        )

    def test_create_makes_creator_owner_with_unique_slug(self):
        second = create_organization(creator=self.owner, name='Test Club', org_type='rso')
        self.assertEqual(second.slug, 'test-club-2')
        self.assertEqual(second.memberships.get().role, OrganizationMembership.Role.OWNER)

    def test_owner_limit_counts_owner_roles_and_survives_transfer(self):
        for number in range(MAX_OWNED_ORGANIZATIONS - 1):
            create_organization(creator=self.owner, name=f'Extra {number}', org_type='rso')
        with self.assertRaises(ValidationError):
            create_organization(creator=self.owner, name='One too many', org_type='rso')
        transfer_organization_ownership(
            actor=self.owner, organization_id=self.organization.pk, new_owner_id=self.admin.pk
        )
        create_organization(creator=self.owner, name='Freed slot', org_type='rso')
        with self.assertRaises(ValidationError):
            create_organization(creator=self.owner, name='Full again', org_type='rso')

    def test_create_view_shows_limit_error(self):
        for number in range(MAX_OWNED_ORGANIZATIONS - 1):
            create_organization(creator=self.owner, name=f'Extra {number}', org_type='rso')
        self.client.force_login(self.owner)
        response = self.client.post(reverse('create_organization'), FORM)
        self.assertContains(response, f'up to {MAX_OWNED_ORGANIZATIONS} organizations')

    def test_non_campus_user_cannot_create(self):
        with self.assertRaises(PermissionDenied):
            create_organization(creator=make_user('plain', campus=False), name='X', org_type='rso')
        self.client.force_login(make_user('plain2', campus=False))
        self.assertRedirects(self.client.post(reverse('create_organization'), FORM), reverse('list_my_organizations'))
        self.assertFalse(Organization.objects.filter(name='Chess Club').exists())

    def test_create_view_with_logo_upload(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('create_organization'), {**FORM, 'logo': png()})
        organization = Organization.objects.get(name='Chess Club')
        self.assertRedirects(response, reverse('show_organization_profile', args=[organization.slug]))
        self.assertTrue(organization.logo.name.startswith('organization_logos/'))

    def test_logo_must_be_an_image(self):
        self.client.force_login(self.owner)
        fake = SimpleUploadedFile('x.png', b'not an image', content_type='image/png')
        response = self.client.post(reverse('create_organization'), {**FORM, 'logo': fake})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Organization.objects.filter(name='Chess Club').exists())

    def test_public_profile_visible_to_guests_without_edit_link(self):
        response = self.client.get(reverse('show_organization_profile', args=[self.organization.slug]))
        self.assertContains(response, 'Test Club')
        self.assertNotContains(response, 'Edit profile')

    def test_only_owner_sees_and_uses_edit(self):
        url = reverse('edit_organization_profile', args=[self.organization.slug])
        profile_url = reverse('show_organization_profile', args=[self.organization.slug])
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(profile_url), 'Edit profile')
        self.assertRedirects(self.client.post(url, {**FORM, 'name': 'Hacked'}), profile_url)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, 'Test Club')

        self.client.force_login(self.owner)
        self.assertContains(self.client.get(profile_url), 'Edit profile')
        self.client.post(url, {**FORM, 'name': 'Renamed'})
        self.organization.refresh_from_db()
        self.assertEqual((self.organization.name, self.organization.slug), ('Renamed', 'test-club'))

    def test_my_organizations_lists_roles(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('list_my_organizations'))
        self.assertContains(response, 'Test Club')
        self.assertContains(response, 'Admin')

    def test_my_organizations_requires_login(self):
        self.assertEqual(self.client.get(reverse('list_my_organizations')).status_code, 302)


class VerificationTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner')
        self.admin = make_user('admin')
        self.platform_admin = User.objects.create_user(
            username='staff', email='staff@example.edu', password=PASSWORD, is_staff=True
        )
        self.organization = create_organization(
            creator=self.owner, name='Test Club', org_type='rso', contact_email='club@example.edu',
            website_url='https://club.example.edu',
        )
        add_organization_member(
            actor=self.owner, organization=self.organization, user=self.admin,
            role=OrganizationMembership.Role.ADMIN,
        )

    def test_only_owner_can_request(self):
        with self.assertRaises(PermissionDenied):
            request_organization_verification(actor=self.admin, organization=self.organization)

    def test_request_needs_email_and_a_link(self):
        bare = create_organization(creator=self.owner, name='Bare', org_type='rso')
        with self.assertRaises(ValidationError):
            request_organization_verification(actor=self.owner, organization=bare)

    def test_one_pending_request_at_a_time(self):
        request_organization_verification(actor=self.owner, organization=self.organization)
        with self.assertRaises(ValidationError):
            request_organization_verification(actor=self.owner, organization=self.organization)

    def test_approve_verifies_and_badge_shows(self):
        pending = request_organization_verification(actor=self.owner, organization=self.organization, note='We are an RSO')
        with self.assertRaises(PermissionDenied):
            review_verification_request(reviewer=self.owner, verification_request=pending, approve=True)
        review_verification_request(reviewer=self.platform_admin, verification_request=pending, approve=True)
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.is_verified)
        response = self.client.get(reverse('show_organization_profile', args=[self.organization.slug]))
        self.assertContains(response, 'verified-badge')
        with self.assertRaises(ValidationError):
            review_verification_request(reviewer=self.platform_admin, verification_request=pending, approve=False)

    def test_reject_allows_a_new_request(self):
        pending = request_organization_verification(actor=self.owner, organization=self.organization)
        review_verification_request(reviewer=self.platform_admin, verification_request=pending, approve=False)
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.is_verified)
        request_organization_verification(actor=self.owner, organization=self.organization)

    def test_request_button_only_for_owner(self):
        url = reverse('show_organization_profile', args=[self.organization.slug])
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(url), 'Request verification')
        self.client.post(reverse('request_organization_verification', args=[self.organization.slug]), {'note': 'hi'})
        self.assertContains(self.client.get(url), 'Verification pending')
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(url), 'Request verification')
