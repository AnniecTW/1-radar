from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.events.models import Event
from apps.events.services import cancel_event, publish_event
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.organizations.models import Organization, OrganizationFollow
from apps.rsvps.services import request_rsvp

Type = Notification.Type


def set_switch(user, key, app, email):
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.notification_prefs = {'notifications': {key: {'app': app, 'email': email}}}
    profile.save()


@override_settings(SITE_URL='https://radar.example.edu')
class NotificationEmailTests(TestCase):
    """FR-48 and FR-59: emails follow the Preferences "Email" switches."""

    def setUp(self):
        self.host = User.objects.create_user(
            username='host', email='host@example.edu', password='x', is_campus_verified=True, is_email_verified=True
        )
        self.organization = Organization.objects.create(
            name='Robotics Club', slug='robotics-club', org_type=Organization.OrgType.RSO, created_by=self.host
        )
        start = timezone.now() + timedelta(days=3)
        self.event = Event.objects.create(
            slug='robot-battle', title='Robot Battle', host_user=self.host, organization=self.organization,
            start_at=start, end_at=start + timedelta(hours=2), location_text='Siebel 1404',
        )
        self.sam = self.user('sam')

    def user(self, name, verified=True):
        return User.objects.create_user(
            username=name, email=f'{name}@example.com', password='x', first_name=name.title(),
            is_email_verified=verified,
        )

    def publish(self):
        with self.captureOnCommitCallbacks(execute=True):
            publish_event(actor=self.host, event_id=self.event.pk)

    def test_rsvp_confirmation_is_emailed_by_default(self):
        self.event.status = Event.Status.PUBLISHED
        self.event.save()
        with self.captureOnCommitCallbacks(execute=True):
            request_rsvp(actor=self.sam, event_id=self.event.pk)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['sam@example.com'])
        self.assertEqual(message.subject, "You're going to Robot Battle")
        self.assertIn('Hi Sam', message.body)
        self.assertIn('Where: Siebel 1404', message.body)
        self.assertIn('https://radar.example.edu/events/robot-battle/', message.body)
        self.assertIn('https://radar.example.edu/accounts/preferences/', message.body)
        row = Notification.objects.get(user=self.sam, type=Type.RSVP_CONFIRMED)
        self.assertIsNotNone(row.emailed_at)

    def test_email_switch_off_sends_no_email_but_keeps_in_app(self):
        set_switch(self.sam, 'rsvp', app=True, email=False)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertIsNotNone(notify(user=self.sam, type=Type.RSVP_CONFIRMED, event=self.event))
        self.assertEqual(mail.outbox, [])

    def test_in_app_off_but_email_on_still_emails(self):
        set_switch(self.sam, 'changes', app=False, email=True)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertIsNone(notify(user=self.sam, type=Type.EVENT_UPDATED, event=self.event,
                                     payload={'changed': 'time'}))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('The time changed.', mail.outbox[0].body)

    def test_unverified_email_gets_no_email(self):
        unverified = self.user('newbie', verified=False)
        with self.captureOnCommitCallbacks(execute=True):
            notify(user=unverified, type=Type.RSVP_CONFIRMED, event=self.event)
        self.assertEqual(mail.outbox, [])

    def test_org_invites_are_not_emailed(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify(user=self.sam, type=Type.ORG_INVITE, organization=self.organization)
        self.assertEqual(mail.outbox, [])

    def test_cancellation_email_includes_the_reason(self):
        self.event.status = Event.Status.PUBLISHED
        self.event.save()
        request_rsvp(actor=self.sam, event_id=self.event.pk)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            cancel_event(actor=self.host, event_id=self.event.pk, reason='The room flooded.')
        self.assertEqual([m.subject for m in mail.outbox], ['Robot Battle was cancelled'])
        self.assertIn('The room flooded.', mail.outbox[0].body)

    def test_new_event_email_is_off_by_default(self):
        OrganizationFollow.objects.create(user=self.sam, organization=self.organization, source='org_page')
        self.publish()
        self.assertEqual(mail.outbox, [])
        self.assertTrue(Notification.objects.filter(user=self.sam, type=Type.FOLLOWED_ORG_NEW_EVENT).exists())

    def test_followers_who_turned_on_email_get_one_each(self):
        for name in ['sam', 'alex']:
            follower = self.sam if name == 'sam' else self.user(name)
            OrganizationFollow.objects.create(user=follower, organization=self.organization, source='org_page')
            set_switch(follower, 'new_events', app=False, email=True)
        muted = self.user('muted')
        OrganizationFollow.objects.create(user=muted, organization=self.organization, source='org_page', notify=False)
        set_switch(muted, 'new_events', app=True, email=True)
        self.publish()
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['alex@example.com', 'sam@example.com'])
        self.assertEqual(mail.outbox[0].subject, 'Robotics Club posted a new event: Robot Battle')

    def test_nothing_is_emailed_when_the_transaction_rolls_back(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify(user=self.sam, type=Type.RSVP_CONFIRMED, event=self.event)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(mail.outbox, [])
