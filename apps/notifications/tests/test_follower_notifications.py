from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.events.models import Event
from apps.events.services import publish_event
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.organizations.models import Organization, OrganizationFollow
from apps.rsvps.services import request_rsvp

NEW_EVENT = Notification.Type.FOLLOWED_ORG_NEW_EVENT


def turn_off_in_app(user, key):
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.notification_prefs = {'notifications': {key: {'app': False, 'email': False}}}
    profile.save()


class FollowerNotificationTests(TestCase):
    """FR-59: followers hear about new events; Preferences "In app" switches are respected."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner', email='owner@example.edu', password='x', is_campus_verified=True
        )
        self.organization = Organization.objects.create(
            name='Robotics Club', slug='robotics-club', org_type=Organization.OrgType.RSO, created_by=self.owner
        )
        self.fan = self.follower('fan')
        start = timezone.now() + timedelta(days=3)
        self.event = Event.objects.create(
            title='Robot Battle', host_user=self.owner, organization=self.organization, start_at=start,
            end_at=start + timedelta(hours=2), location_text='Siebel 1404',
        )

    def follower(self, name, **extra):
        user = User.objects.create_user(username=name, email=f'{name}@example.com', password='x')
        OrganizationFollow.objects.create(user=user, organization=self.organization, source='org_page', **extra)
        return user

    def notified(self):
        return set(Notification.objects.filter(type=NEW_EVENT, event=self.event).values_list('user__username', flat=True))

    def test_followers_are_notified_when_an_event_is_published(self):
        self.follower('second')
        publish_event(actor=self.owner, event_id=self.event.pk)
        self.assertEqual(self.notified(), {'fan', 'second'})
        row = Notification.objects.get(user=self.fan, type=NEW_EVENT)
        self.assertEqual(row.organization, self.organization)

    def test_nobody_is_notified_while_it_is_a_draft(self):
        self.assertEqual(self.notified(), set())

    def test_muted_follow_is_skipped(self):
        self.follower('muted', notify=False)
        publish_event(actor=self.owner, event_id=self.event.pk)
        self.assertEqual(self.notified(), {'fan'})

    def test_unlisted_event_notifies_nobody(self):
        self.event.visibility = Event.Visibility.UNLISTED
        self.event.save()
        publish_event(actor=self.owner, event_id=self.event.pk)
        self.assertEqual(self.notified(), set())

    def test_publisher_and_deleted_accounts_are_skipped(self):
        OrganizationFollow.objects.create(user=self.owner, organization=self.organization, source='org_page')
        gone = self.follower('gone')
        gone.is_active = False
        gone.save()
        publish_event(actor=self.owner, event_id=self.event.pk)
        self.assertEqual(self.notified(), {'fan'})

    def test_in_app_switch_off_for_new_events_is_respected(self):
        turn_off_in_app(self.fan, 'new_events')
        self.follower('second')
        publish_event(actor=self.owner, event_id=self.event.pk)
        self.assertEqual(self.notified(), {'second'})

    def test_personal_event_notifies_nobody(self):
        self.event.organization = None
        self.event.save()
        publish_event(actor=self.owner, event_id=self.event.pk)
        self.assertEqual(self.notified(), set())


class PreferenceSwitchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sam', email='sam@example.com', password='x')

    def test_switch_off_skips_only_that_kind(self):
        turn_off_in_app(self.user, 'rsvp')
        self.assertIsNone(notify(user=self.user, type=Notification.Type.RSVP_CONFIRMED))
        self.assertIsNotNone(notify(user=self.user, type=Notification.Type.WAITLIST_JOINED))

    def test_default_is_on_even_without_a_profile(self):
        Profile.objects.filter(user=self.user).delete()
        self.user = User.objects.get(pk=self.user.pk)
        self.assertIsNotNone(notify(user=self.user, type=Notification.Type.RSVP_CONFIRMED))

    def test_org_invites_have_no_switch_and_always_arrive(self):
        turn_off_in_app(self.user, 'rsvp')
        self.assertIsNotNone(notify(user=self.user, type=Notification.Type.ORG_INVITE))

    def test_rsvp_confirmation_respects_the_switch(self):
        host = User.objects.create_user(username='host', email='host@example.edu', password='x', is_campus_verified=True)
        start = timezone.now() + timedelta(days=2)
        event = Event.objects.create(
            slug='chess', title='Chess', host_user=host, start_at=start, end_at=start + timedelta(hours=1),
            location_text='Room 1', status=Event.Status.PUBLISHED,
        )
        self.user.is_email_verified = True
        self.user.save()
        turn_off_in_app(self.user, 'rsvp')
        request_rsvp(actor=self.user, event_id=event.pk)
        self.assertFalse(Notification.objects.filter(user=self.user, type=Notification.Type.RSVP_CONFIRMED).exists())
