import io
import tempfile
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.events.models import Event, EventCheckInStaff
from apps.notifications.models import Notification
from apps.organizations.models import Organization, OrganizationMembership
from apps.organizations.services import (
    MAX_OWNED_ORGANIZATIONS, add_member_by_email, add_organization_member, change_member_role, create_organization, request_organization_verification,
    delete_organization, leave_organization, review_verification_request, transfer_organization_ownership,
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


class MemberManagementTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner')
        self.admin = make_user('admin')
        self.staff = make_user('staff')
        self.organization = create_organization(creator=self.owner, name='Test Club', org_type='rso')
        self.role = OrganizationMembership.Role
        for user, role in ((self.admin, self.role.ADMIN), (self.staff, self.role.CHECKIN_STAFF)):
            add_organization_member(actor=self.owner, organization=self.organization, user=user, role=role)
        self.url = reverse('manage_organization_members', args=[self.organization.slug])

    def membership(self, user):
        return OrganizationMembership.objects.get(organization=self.organization, user=user)

    def test_only_owner_sees_members_page(self):
        self.assertContains(self.client_login(self.owner).get(self.url), 'Add a member')
        for user in (self.admin, self.staff):
            response = self.client_login(user).get(self.url)
            self.assertRedirects(response, reverse('show_organization_profile', args=[self.organization.slug]))
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def client_login(self, user):
        self.client.force_login(user)
        return self.client

    def test_add_by_email_requires_existing_campus_account_and_notifies(self):
        newcomer = make_user('newcomer')
        membership = add_member_by_email(
            actor=self.owner, organization=self.organization, email='NEWCOMER@example.edu', role=self.role.ADMIN
        )
        self.assertEqual(membership.user, newcomer)
        self.assertTrue(Notification.objects.filter(
            user=newcomer, organization=self.organization, type=Notification.Type.ORG_INVITE).exists())
        make_user('plain', campus=False)
        for email, message in (('nobody@example.edu', 'No Radar account'), ('plain@example.edu', 'verified campus email'),
                               ('admin@example.edu', 'already a member')):
            with self.subTest(email=email), self.assertRaisesMessage(ValidationError, message):
                add_member_by_email(actor=self.owner, organization=self.organization, email=email, role=self.role.ADMIN)

    def test_non_owner_cannot_add_change_or_remove(self):
        for actor in (self.admin, self.staff):
            with self.assertRaises(PermissionDenied):
                add_member_by_email(actor=actor, organization=self.organization, email='owner@example.edu', role=self.role.ADMIN)
            with self.assertRaises(PermissionDenied):
                change_member_role(actor=actor, membership=self.membership(self.staff), role=self.role.ADMIN)
        self.client_login(self.admin).post(
            reverse('remove_organization_member', args=[self.organization.slug, self.membership(self.staff).pk]))
        self.assertTrue(OrganizationMembership.objects.filter(user=self.staff).exists())

    def test_re_adding_the_owner_does_not_demote_them(self):
        with self.assertRaises(ValidationError):
            add_organization_member(actor=self.owner, organization=self.organization, user=self.owner, role=self.role.ADMIN)
        self.assertEqual(self.membership(self.owner).role, self.role.OWNER)

    def test_change_role_via_view_and_owner_is_protected(self):
        role_url = reverse('set_organization_member_role', args=[self.organization.slug, self.membership(self.staff).pk])
        self.client_login(self.owner).post(role_url, {'role': 'admin'})
        self.assertEqual(self.membership(self.staff).role, self.role.ADMIN)
        with self.assertRaises(ValidationError):
            change_member_role(actor=self.owner, membership=self.membership(self.owner), role=self.role.ADMIN)
        with self.assertRaises(ValidationError):
            change_member_role(actor=self.owner, membership=self.membership(self.staff), role='owner')

    def test_removing_staff_or_promoting_to_admin_clears_event_assignments(self):
        start = timezone.now() + timedelta(days=2)
        event = Event.objects.create(
            slug='e1', title='E1', host_user=self.owner, organization=self.organization, start_at=start,
            end_at=start + timedelta(hours=1), location_text='Room', status=Event.Status.PUBLISHED,
        )
        EventCheckInStaff.objects.create(event=event, user=self.staff, assigned_by=self.owner)
        change_member_role(actor=self.owner, membership=self.membership(self.staff), role=self.role.ADMIN)
        self.assertFalse(EventCheckInStaff.objects.exists())

        change_member_role(actor=self.owner, membership=self.membership(self.staff), role=self.role.CHECKIN_STAFF)
        EventCheckInStaff.objects.create(event=event, user=self.staff, assigned_by=self.owner)
        self.client_login(self.owner).post(
            reverse('remove_organization_member', args=[self.organization.slug, self.membership(self.staff).pk]))
        self.assertFalse(OrganizationMembership.objects.filter(user=self.staff).exists())
        self.assertFalse(EventCheckInStaff.objects.exists())

    def test_owner_cannot_be_removed_and_profile_links_to_members(self):
        owner_pk = self.membership(self.owner).pk
        self.client_login(self.owner).post(reverse('remove_organization_member', args=[self.organization.slug, owner_pk]))
        self.assertTrue(OrganizationMembership.objects.filter(pk=owner_pk).exists())
        profile = self.client.get(reverse('show_organization_profile', args=[self.organization.slug]))
        self.assertContains(profile, self.url)


class OrganizationExitTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner')
        self.admin = make_user('admin')
        self.staff = make_user('staff')
        self.organization = create_organization(creator=self.owner, name='Exit Club', org_type='rso')
        self.role = OrganizationMembership.Role
        for user, role in ((self.admin, self.role.ADMIN), (self.staff, self.role.CHECKIN_STAFF)):
            add_organization_member(actor=self.owner, organization=self.organization, user=user, role=role)

    def event(self, *, days, status=Event.Status.PUBLISHED, slug='ev'):
        start = timezone.now() + timedelta(days=days)
        return Event.objects.create(
            slug=slug, title='Ev', host_user=self.owner, organization=self.organization, start_at=start,
            end_at=start + timedelta(hours=1), location_text='Room', status=status,
        )

    def role_of(self, user):
        return OrganizationMembership.objects.get(organization=self.organization, user=user).role

    def test_transfer_swaps_roles_notifies_and_is_owner_only(self):
        transfer_organization_ownership(actor=self.owner, organization_id=self.organization.pk, new_owner_id=self.staff.pk)
        self.assertEqual(self.role_of(self.staff), self.role.OWNER)
        self.assertEqual(self.role_of(self.owner), self.role.ADMIN)
        self.assertTrue(Notification.objects.filter(user=self.staff, organization=self.organization).exists())
        with self.assertRaises(PermissionDenied):
            transfer_organization_ownership(actor=self.owner, organization_id=self.organization.pk, new_owner_id=self.admin.pk)
        with self.assertRaises(ValidationError):
            transfer_organization_ownership(
                actor=self.staff, organization_id=self.organization.pk, new_owner_id=make_user('stranger').pk)

    def test_transfer_respects_owner_cap_of_new_owner(self):
        for number in range(MAX_OWNED_ORGANIZATIONS):
            create_organization(creator=self.admin, name=f'Admin Club {number}', org_type='rso')
        with self.assertRaises(ValidationError):
            transfer_organization_ownership(actor=self.owner, organization_id=self.organization.pk, new_owner_id=self.admin.pk)
        self.assertEqual(self.role_of(self.owner), self.role.OWNER)

    def test_transfer_view_redirects_and_non_owner_is_blocked(self):
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.admin)
        url = reverse('transfer_organization_ownership', args=[self.organization.slug, membership.pk])
        self.client.force_login(self.staff)
        self.client.post(url)
        self.assertEqual(self.role_of(self.admin), self.role.ADMIN)
        self.client.force_login(self.owner)
        self.client.post(url)
        self.assertEqual(self.role_of(self.admin), self.role.OWNER)

    def test_leave_clears_assignments_and_owner_cannot_leave(self):
        event = self.event(days=2)
        EventCheckInStaff.objects.create(event=event, user=self.staff, assigned_by=self.owner)
        self.client.force_login(self.staff)
        self.client.post(reverse('leave_organization', args=[self.organization.slug]))
        self.assertFalse(OrganizationMembership.objects.filter(user=self.staff, organization=self.organization).exists())
        self.assertFalse(EventCheckInStaff.objects.exists())
        with self.assertRaises(ValidationError):
            leave_organization(user=self.owner, organization=self.organization)
        with self.assertRaises(ValidationError):
            leave_organization(user=make_user('outsider'), organization=self.organization)

    def test_delete_blocked_by_upcoming_or_running_published_events(self):
        running = self.event(days=0, slug='running')
        Event.objects.filter(pk=running.pk).update(start_at=timezone.now() - timedelta(hours=1),
                                                   end_at=timezone.now() + timedelta(hours=1))
        with self.assertRaisesMessage(ValidationError, 'upcoming event'):
            delete_organization(actor=self.owner, organization=self.organization, confirm_name='Exit Club')
        self.assertTrue(Organization.objects.filter(pk=self.organization.pk).exists())

    def test_delete_requires_owner_and_exact_name_then_detaches_past_and_draft_events(self):
        past = self.event(days=-3, slug='past')
        draft = self.event(days=5, status=Event.Status.DRAFT, slug='draft')
        with self.assertRaises(PermissionDenied):
            delete_organization(actor=self.admin, organization=self.organization, confirm_name='Exit Club')
        with self.assertRaises(ValidationError):
            delete_organization(actor=self.owner, organization=self.organization, confirm_name='exit club')
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('delete_organization', args=[self.organization.slug]), {'confirm_name': 'Exit Club'})
        self.assertRedirects(response, reverse('list_my_organizations'))
        self.assertFalse(Organization.objects.filter(pk=self.organization.pk).exists())
        for event in (past, draft):
            event.refresh_from_db()
            self.assertIsNone(event.organization_id)
