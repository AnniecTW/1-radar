import io
import tempfile

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.organizations.services import add_organization_member, create_organization

PASSWORD = 'Strong-Pass-123'
FORM = {'name': 'Chess Club', 'org_type': 'rso', 'description': 'We play chess.'}


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
