from datetime import timedelta

from django.contrib import admin
from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.attendance.models import CheckIn
from apps.events.models import Event, EventCheckInStaff
from apps.organizations.models import Organization, OrganizationMembership
from apps.rsvps.models import RSVP, Ticket
from apps.attendance.services import check_in_with_ticket
from apps.analytics.models import EventDailyStats
from apps.engagement.models import EventOutboundClick
from apps.organizations.models import OrganizationFollow


class CheckInServiceTests(TestCase):
    def setUp(self):
        self.owner = self.make_user('owner@checkin.test')
        self.staff = self.make_user('staff@checkin.test')
        self.unassigned = self.make_user('unassigned@checkin.test')
        self.attendee = self.make_user('attendee@checkin.test')
        self.organization = Organization.objects.create(
            name='Check-in Test Org', slug='checkin-test-org',
            org_type=Organization.OrgType.RSO, created_by=self.owner,
        )
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.staff,
            role=OrganizationMembership.Role.CHECKIN_STAFF,
        )
        now = timezone.now()
        self.event = Event.objects.create(
            slug='checkin-test-event', title='Check-in Test Event', host_user=self.owner,
            organization=self.organization, start_at=now + timedelta(days=1),
            end_at=now + timedelta(days=1, hours=1), location_text='Room A',
            location=Point(-88.22, 40.10, srid=4326), status=Event.Status.PUBLISHED,
        )
        EventCheckInStaff.objects.create(event=self.event, user=self.staff, assigned_by=self.owner)
        self.rsvp = RSVP.objects.create(event=self.event, user=self.attendee, status=RSVP.Status.GOING)
        self.ticket = Ticket.objects.create(rsvp=self.rsvp, code='valid-test-ticket')

    @staticmethod
    def make_user(email):
        return User.objects.create_user(
            username=email.split('@')[0], email=email,
            password='test-password-42', is_email_verified=True,
        )

    def test_assigned_staff_can_check_in_ticket_once(self):
        checkin = check_in_with_ticket(
            actor=self.staff, event_id=self.event.pk, ticket_code=self.ticket.code
        )
        self.assertEqual(checkin.user, self.attendee)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.USED)
        with self.assertRaises(ValidationError):
            check_in_with_ticket(actor=self.staff, event_id=self.event.pk, ticket_code=self.ticket.code)

    def test_unassigned_staff_and_platform_admin_are_denied(self):
        with self.assertRaises(PermissionDenied):
            check_in_with_ticket(
                actor=self.unassigned, event_id=self.event.pk, ticket_code=self.ticket.code
            )
        platform_admin = self.make_user('platform@checkin.test')
        platform_admin.is_staff = True
        platform_admin.is_superuser = True
        platform_admin.save()
        with self.assertRaises(PermissionDenied):
            check_in_with_ticket(
                actor=platform_admin, event_id=self.event.pk, ticket_code=self.ticket.code
            )

    def test_ticket_for_different_event_is_rejected(self):
        other_event = Event.objects.create(
            slug='other-checkin-event', title='Other Check-in Event', host_user=self.owner,
            organization=self.organization, start_at=self.event.start_at,
            end_at=self.event.end_at, location_text='Room B',
            location=Point(-88.22, 40.11, srid=4326), status=Event.Status.PUBLISHED,
        )
        with self.assertRaises(ValidationError):
            check_in_with_ticket(
                actor=self.owner, event_id=other_event.pk, ticket_code=self.ticket.code
            )

    def test_admin_site_does_not_expose_attendee_records(self):
        self.assertNotIn(CheckIn, admin.site._registry)
        self.assertNotIn(RSVP, admin.site._registry)
        self.assertNotIn(Ticket, admin.site._registry)
        self.assertNotIn(EventDailyStats, admin.site._registry)
        self.assertNotIn(OrganizationFollow, admin.site._registry)
        self.assertNotIn(EventOutboundClick, admin.site._registry)
