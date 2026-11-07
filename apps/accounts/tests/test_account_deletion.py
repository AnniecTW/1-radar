from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.exceptions import AccountDeletionBlockedError
from apps.accounts.models import User
from apps.accounts.selectors import get_account_deletion_blockers
from apps.accounts.services import delete_account
from apps.engagement.models import EventLike, EventSave
from apps.events.models import Event
from apps.notifications.models import Notification
from apps.organizations.models import Organization, OrganizationFollow, OrganizationMembership
from apps.organizations.services import (
    add_organization_member, create_organization, delete_organization, follow_organization,
    transfer_organization_ownership,
)
from apps.rsvps.models import RSVP, Ticket
from apps.rsvps.services import request_rsvp

PASSWORD = 'Strong-Pass-123'


def make_user(name):
    return User.objects.create_user(
        username=name, email=f'{name}@example.edu', password=PASSWORD, first_name=name, is_campus_verified=True
    )


def make_event(host, *, days, organization=None, status=Event.Status.PUBLISHED, slug='ev', capacity=None):
    start = timezone.now() + timedelta(days=days)
    return Event.objects.create(
        slug=slug, title=slug.title(), host_user=host, organization=organization, start_at=start,
        end_at=start + timedelta(hours=1), location_text='Room', status=status, capacity=capacity,
    )


class AccountDeletionBlockerTests(TestCase):
    def setUp(self):
        self.user = make_user('sam')
        self.other = make_user('other')

    def test_no_blockers_for_a_plain_attendee(self):
        self.assertFalse(get_account_deletion_blockers(self.user)['has_blockers'])

    def test_owner_is_blocked_until_ownership_is_transferred(self):
        organization = create_organization(creator=self.user, name='Club', org_type='rso')
        add_organization_member(actor=self.user, organization=organization, user=self.other, role='admin')
        blockers = get_account_deletion_blockers(self.user)
        self.assertEqual(blockers['owned_organizations'], [organization])
        with self.assertRaises(AccountDeletionBlockedError):
            delete_account(user=self.user, password=PASSWORD)
        transfer_organization_ownership(actor=self.user, organization_id=organization.pk, new_owner_id=self.other.pk)
        # The former Owner is now an Admin, which still blocks until they leave.
        blockers = get_account_deletion_blockers(self.user)
        self.assertEqual([m.organization for m in blockers['memberships']], [organization])
        self.assertEqual(blockers['owned_organizations'], [])

    def test_admin_and_staff_must_leave(self):
        organization = create_organization(creator=self.other, name='Club', org_type='rso')
        add_organization_member(actor=self.other, organization=organization, user=self.user, role='checkin_staff')
        with self.assertRaises(AccountDeletionBlockedError):
            delete_account(user=self.user, password=PASSWORD)

    def test_individual_host_blocked_only_by_upcoming_or_running_published_events(self):
        past = make_event(self.user, days=-2, slug='past')
        draft = make_event(self.user, days=3, status=Event.Status.DRAFT, slug='draft')
        cancelled = make_event(self.user, days=3, status=Event.Status.CANCELLED, slug='cancelled')
        self.assertFalse(get_account_deletion_blockers(self.user)['has_blockers'])
        running = make_event(self.user, days=0, slug='running')
        Event.objects.filter(pk=running.pk).update(
            start_at=timezone.now() - timedelta(hours=1), end_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(get_account_deletion_blockers(self.user)['hosted_events'], [running])
        running.delete()
        make_event(self.user, days=4, slug='upcoming')
        self.assertTrue(get_account_deletion_blockers(self.user)['has_blockers'])
        self.assertTrue(all(e not in get_account_deletion_blockers(self.user)['hosted_events']
                            for e in (past, draft, cancelled)))

    def test_organization_event_hosted_by_user_is_not_an_individual_host_blocker(self):
        organization = create_organization(creator=self.other, name='Club', org_type='rso')
        make_event(self.user, days=3, organization=organization)
        self.assertFalse(get_account_deletion_blockers(self.user)['has_blockers'])

    def test_platform_admin_is_blocked(self):
        self.user.is_staff = True
        self.user.save()
        self.assertTrue(get_account_deletion_blockers(self.user)['is_platform_admin'])

    def test_deletion_screen_lists_blockers_and_hides_the_form(self):
        organization = create_organization(creator=self.user, name='Club', org_type='rso')
        self.client.force_login(self.user)
        response = self.client.get(reverse('delete_account'))
        self.assertContains(response, 'Transfer ownership')
        self.assertContains(response, organization.name)
        self.assertNotContains(response, 'Confirm with your password')
        self.client.post(reverse('delete_account'), {'password': PASSWORD})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.user = make_user('sam')
        self.waiter = make_user('waiter')
        self.host = make_user('host')
        self.organization = create_organization(creator=self.host, name='Club', org_type='rso')

    def test_wrong_password_changes_nothing(self):
        with self.assertRaises(ValidationError):
            delete_account(user=self.user, password='nope')
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_anonymizes_and_removes_personal_data(self):
        event = make_event(self.host, days=3, organization=self.organization)
        follow_organization(user=self.user, organization=self.organization, source='org_page')
        EventLike.objects.create(user=self.user, event=event)
        EventSave.objects.create(user=self.user, event=event)
        Notification.objects.create(user=self.user, type=Notification.Type.REMINDER, event=event)
        self.client.force_login(self.user)
        response = self.client.post(reverse('delete_account'), {'password': PASSWORD})
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual((self.user.first_name, self.user.campus_email), ('', None))
        self.assertTrue(self.user.email.endswith('@deleted.invalid'))
        self.assertFalse(self.user.has_usable_password())
        self.assertEqual(self.user.profile.display_name, '')
        self.assertFalse(OrganizationFollow.objects.filter(user=self.user).exists())
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.follower_count, 0)
        self.assertFalse(EventLike.objects.filter(user=self.user).exists())
        self.assertFalse(EventSave.objects.filter(user=self.user).exists())
        self.assertFalse(Notification.objects.filter(user=self.user).exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.post(reverse('login'), {'email': 'sam@example.edu', 'password': PASSWORD}).status_code, 200)

    def test_cancels_upcoming_rsvp_voids_ticket_and_promotes_waitlist(self):
        event = make_event(self.host, days=3, organization=self.organization, capacity=1)
        going = request_rsvp(event_id=event.pk, actor=self.user)
        waiting = request_rsvp(event_id=event.pk, actor=self.waiter)
        self.assertEqual(waiting.status, RSVP.Status.WAITLISTED)
        delete_account(user=self.user, password=PASSWORD)
        going.refresh_from_db()
        waiting.refresh_from_db()
        self.assertEqual(going.status, RSVP.Status.CANCELLED)
        self.assertEqual(Ticket.objects.get(rsvp=going).status, Ticket.Status.VOID)
        self.assertEqual(waiting.status, RSVP.Status.GOING)

    def test_past_rsvps_and_hosted_past_events_survive_the_anonymized_row(self):
        past = make_event(self.user, days=-3, slug='past')
        RSVP.objects.create(event=past, user=self.user, status=RSVP.Status.GOING)
        draft = make_event(self.user, days=5, status=Event.Status.DRAFT, slug='draft')
        delete_account(user=self.user, password=PASSWORD)
        past.refresh_from_db()
        self.assertEqual(past.host_user_id, self.user.pk)
        self.assertTrue(RSVP.objects.filter(event=past, user=self.user).exists())
        self.assertFalse(Event.objects.filter(pk=draft.pk).exists())

    def test_email_can_be_reused_after_deletion(self):
        delete_account(user=self.user, password=PASSWORD)
        User.objects.create_user(username='sam2', email='sam@example.edu', password=PASSWORD)


class OrganizationDeletionBlockerTests(TestCase):
    """Organization deletion is refused while a published event is upcoming or running."""

    def setUp(self):
        self.owner = make_user('owner')
        self.organization = create_organization(creator=self.owner, name='Doomed Club', org_type='rso')

    def attempt(self):
        return delete_organization(actor=self.owner, organization=self.organization, confirm_name='Doomed Club')

    def test_upcoming_published_event_blocks(self):
        make_event(self.owner, days=2, organization=self.organization)
        with self.assertRaisesMessage(ValidationError, '1 upcoming event'):
            self.attempt()
        self.assertTrue(Organization.objects.filter(pk=self.organization.pk).exists())

    def test_running_event_blocks(self):
        event = make_event(self.owner, days=0, organization=self.organization)
        Event.objects.filter(pk=event.pk).update(
            start_at=timezone.now() - timedelta(minutes=30), end_at=timezone.now() + timedelta(minutes=30))
        with self.assertRaises(ValidationError):
            self.attempt()

    def test_draft_cancelled_and_past_events_do_not_block(self):
        make_event(self.owner, days=2, organization=self.organization, status=Event.Status.DRAFT, slug='d')
        make_event(self.owner, days=2, organization=self.organization, status=Event.Status.CANCELLED, slug='c')
        make_event(self.owner, days=-2, organization=self.organization, slug='p')
        self.attempt()
        self.assertFalse(Organization.objects.filter(pk=self.organization.pk).exists())
        self.assertEqual(Event.objects.filter(organization__isnull=True).count(), 3)

    def test_members_page_hides_delete_form_while_blocked(self):
        make_event(self.owner, days=2, organization=self.organization)
        self.client.force_login(self.owner)
        response = self.client.get(reverse('manage_organization_members', args=[self.organization.slug]))
        self.assertContains(response, 'cannot delete')
        self.assertNotContains(response, 'name="confirm_name"')
