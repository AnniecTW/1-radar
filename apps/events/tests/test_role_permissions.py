from datetime import timedelta

from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.attendance.permissions import user_can_check_in_attendees
from apps.analytics.permissions import user_can_export_attendees, user_can_view_analytics
from apps.events.models import Event, EventCheckInStaff
from apps.events.services import assign_checkin_staff, publish_event
from apps.events.permissions import user_can_edit_event
from apps.organizations.models import Organization, OrganizationMembership
from apps.organizations.permissions import user_can_manage_members
from apps.organizations.services import add_organization_member, transfer_organization_ownership


class RolePermissionTests(TestCase):
    def setUp(self):
        self.owner = self.make_user('owner@example.edu', campus=True)
        self.admin = self.make_user('admin@example.edu', campus=True)
        self.staff = self.make_user('staff@example.edu', campus=True)
        self.attendee = self.make_user('attendee@example.edu', campus=True)
        self.platform_admin = self.make_user('platform@example.edu', staff=True, superuser=True)
        self.organization = Organization.objects.create(
            name='Robotics Club', slug='robotics-club', org_type=Organization.OrgType.RSO,
            created_by=self.owner,
        )
        self.owner_membership = self.organization.memberships.get(user=self.owner)
        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN
        )
        self.staff_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.staff, role=OrganizationMembership.Role.CHECKIN_STAFF
        )
        now = timezone.now()
        self.event = Event.objects.create(
            slug='robotics-demo', title='Robotics Demo', host_user=self.owner,
            organization=self.organization, start_at=now + timedelta(days=1),
            end_at=now + timedelta(days=1, hours=2), location_text='Engineering Hall',
            location=Point(-88.2272, 40.1020, srid=4326), status=Event.Status.PUBLISHED,
        )
        EventCheckInStaff.objects.create(
            event=self.event, user=self.staff, assigned_by=self.owner
        )

    @staticmethod
    def make_user(email, campus=False, staff=False, superuser=False):
        return User.objects.create_user(
            username=email.split('@')[0], email=email, password='test-password-42', is_email_verified=True,
            is_campus_verified=campus, is_staff=staff, is_superuser=superuser,
        )

    def test_owner_and_admin_event_permissions_are_distinct(self):
        self.assertTrue(user_can_manage_members(self.owner, self.organization))
        self.assertFalse(user_can_manage_members(self.admin, self.organization))
        self.assertTrue(user_can_edit_event(self.admin, self.event))
        self.assertTrue(user_can_view_analytics(self.admin, self.event))
        self.assertFalse(user_can_export_attendees(self.admin, self.event))

    def test_assigned_staff_can_check_in_but_not_manage_event(self):
        self.assertTrue(user_can_check_in_attendees(self.staff, self.event))
        self.assertFalse(user_can_edit_event(self.staff, self.event))
        self.assertFalse(user_can_view_analytics(self.staff, self.event))
        self.assertFalse(user_can_export_attendees(self.staff, self.event))

    def test_platform_admin_does_not_gain_organization_or_attendee_permissions(self):
        self.assertFalse(user_can_manage_members(self.platform_admin, self.organization))
        self.assertFalse(user_can_edit_event(self.platform_admin, self.event))
        self.assertFalse(user_can_check_in_attendees(self.platform_admin, self.event))
        self.assertFalse(user_can_view_analytics(self.platform_admin, self.event))
        self.assertFalse(user_can_export_attendees(self.platform_admin, self.event))

    def test_member_changes_and_ownership_transfer_require_owner(self):
        with self.assertRaises(PermissionDenied):
            add_organization_member(
                actor=self.admin, organization=self.organization,
                user=self.attendee, role=OrganizationMembership.Role.ADMIN,
            )
        transfer_organization_ownership(
            actor=self.owner, organization_id=self.organization.pk, new_owner_id=self.admin.pk
        )
        self.assertTrue(user_can_manage_members(self.admin, self.organization))
        self.assertFalse(user_can_manage_members(self.owner, self.organization))

    def test_individual_event_is_managed_only_by_its_host(self):
        personal_event = Event.objects.create(
            slug='personal-demo', title='Personal Demo', host_user=self.owner,
            start_at=self.event.start_at, end_at=self.event.end_at,
            location_text='Library', location=Point(-88.23, 40.10, srid=4326),
            status=Event.Status.PUBLISHED,
        )
        self.assertTrue(user_can_edit_event(self.owner, personal_event))
        self.assertFalse(user_can_edit_event(self.admin, personal_event))

    def test_non_campus_user_cannot_be_added_as_org_member(self):
        non_campus = self.make_user('visitor@example.net')
        with self.assertRaises(ValidationError):
            add_organization_member(
                actor=self.owner, organization=self.organization,
                user=non_campus, role=OrganizationMembership.Role.ADMIN,
            )

    def test_admin_can_assign_org_staff_but_unassigned_user_cannot_publish(self):
        another_staff = self.make_user('another-staff@example.edu', campus=True)
        OrganizationMembership.objects.create(
            organization=self.organization, user=another_staff,
            role=OrganizationMembership.Role.CHECKIN_STAFF,
        )
        assignment = assign_checkin_staff(
            actor=self.admin, event_id=self.event.pk, user_id=another_staff.pk
        )
        self.assertEqual(assignment.user, another_staff)

        draft = Event.objects.create(
            title='Draft Event', host_user=self.owner, organization=self.organization,
            start_at=timezone.now() + timedelta(days=2),
            end_at=timezone.now() + timedelta(days=2, hours=1), location_text='Room 102',
        )
        with self.assertRaises(PermissionDenied):
            publish_event(actor=self.staff, event_id=draft.pk)
        published = publish_event(actor=self.admin, event_id=draft.pk)
        self.assertEqual(published.status, Event.Status.PUBLISHED)
        self.assertTrue(published.slug)
