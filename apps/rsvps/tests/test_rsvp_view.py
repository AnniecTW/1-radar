from datetime import timedelta

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event
from apps.rsvps.models import RSVP, Ticket
from apps.rsvps.selectors import get_rsvp_state

PASSWORD = 'Strong-Pass-123'


class RSVPTestCase(TestCase):
    def setUp(self):
        self.host = self.make_user('host')
        self.user = self.make_user('sam')
        self.client.force_login(self.user)

    def make_user(self, name, **flags):
        flags = {'is_email_verified': True, 'is_campus_verified': True, **flags}
        return User.objects.create_user(username=name, email=f'{name}@example.edu', password=PASSWORD, **flags)

    def make_event(self, *, hours_away=72, **fields):
        start = timezone.now() + timedelta(hours=hours_away)
        fields = {'status': Event.Status.PUBLISHED, **fields}
        return Event.objects.create(
            slug=f'event-{Event.objects.count()}', title='Test Event', host_user=self.host,
            start_at=start, end_at=start + timedelta(hours=2), location_text='Room 1', **fields,
        )

    def post(self, event, action='rsvp', **extra):
        data = {'action': action, 'next': '/accounts/profile/', **extra}
        return self.client.post(reverse('rsvp', args=[event.pk]), data)

    def state(self, event, user=None):
        return get_rsvp_state(user or self.user, event, timezone.now())


class RSVPViewTests(RSVPTestCase):
    def test_rsvp_makes_you_going_with_a_ticket_and_returns_to_the_page(self):
        event = self.make_event()
        response = self.post(event)
        self.assertRedirects(response, '/accounts/profile/', fetch_redirect_response=False)
        rsvp = RSVP.objects.get(event=event, user=self.user)
        self.assertEqual(rsvp.status, RSVP.Status.GOING)
        self.assertTrue(Ticket.objects.filter(rsvp=rsvp).exists())

    def test_rsvping_twice_keeps_one_rsvp(self):
        event = self.make_event()
        self.post(event)
        self.post(event)
        self.assertEqual(RSVP.objects.filter(event=event, user=self.user).count(), 1)

    def test_cancel(self):
        event = self.make_event()
        self.post(event)
        self.post(event, 'cancel')
        self.assertEqual(RSVP.objects.get(event=event, user=self.user).status, RSVP.Status.CANCELLED)

    def test_cancel_without_an_rsvp_shows_a_message(self):
        response = self.post(self.make_event(), 'cancel')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RSVP.objects.exists())

    def test_full_event_puts_you_on_the_waitlist(self):
        event = self.make_event(capacity=1)
        RSVP.objects.create(event=event, user=self.host, status=RSVP.Status.GOING)
        self.post(event)
        rsvp = RSVP.objects.get(event=event, user=self.user)
        self.assertEqual((rsvp.status, rsvp.waitlist_position), (RSVP.Status.WAITLISTED, 1))

    def test_rsvping_again_on_the_waitlist_keeps_your_place(self):
        event = self.make_event(capacity=1)
        RSVP.objects.create(event=event, user=self.host, status=RSVP.Status.GOING)
        other = self.make_user('other')
        self.post(event)
        self.client.force_login(other)
        self.post(event)
        self.client.force_login(self.user)
        self.post(event)
        positions = dict(RSVP.objects.filter(event=event, status=RSVP.Status.WAITLISTED).values_list('user', 'waitlist_position'))
        self.assertEqual(positions, {self.user.pk: 1, other.pk: 2})

    def test_cancelling_promotes_the_waitlist(self):
        event = self.make_event(capacity=1)
        self.post(event)
        other = self.make_user('other')
        self.client.force_login(other)
        self.post(event)
        self.client.force_login(self.user)
        self.post(event, 'cancel')
        self.assertEqual(RSVP.objects.get(event=event, user=other).status, RSVP.Status.GOING)

    def test_guests_are_sent_to_sign_in_and_back(self):
        self.client.logout()
        response = self.post(self.make_event())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.assertIn('next=%2Faccounts%2Fprofile%2F', response.url)
        self.assertFalse(RSVP.objects.exists())

    def test_unverified_email_cannot_rsvp(self):
        self.client.force_login(self.make_user('new', is_email_verified=False))
        self.post(self.make_event())
        self.assertFalse(RSVP.objects.exists())

    def test_paid_events_take_no_rsvp(self):
        self.post(self.make_event(is_free=False, price_text='$5', external_url='https://tickets.example.com'))
        self.assertFalse(RSVP.objects.exists())

    def test_drop_in_events_mark_you_interested(self):
        event = self.make_event(rsvp_required=False)
        self.post(event)
        self.assertEqual(RSVP.objects.get(event=event, user=self.user).status, RSVP.Status.INTERESTED)

    def test_unsafe_next_urls_are_ignored(self):
        response = self.post(self.make_event(), next='https://evil.example.com/')
        self.assertEqual(response.url, reverse('dashboard'))

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse('rsvp', args=[self.make_event().pk])).status_code, 405)


class RSVPStateTests(RSVPTestCase):
    def test_states_follow_the_event_and_the_person(self):
        self.assertEqual(self.state(self.make_event())['state'], 'rsvp')
        self.assertEqual(self.state(self.make_event(rsvp_required=False))['state'], 'drop_in')
        self.assertEqual(self.state(self.make_event(is_free=False, price_text='$5'))['state'], 'paid')
        self.assertEqual(self.state(self.make_event(hours_away=-5))['state'], 'ended')
        self.assertEqual(self.state(self.make_event(status=Event.Status.CANCELLED))['state'], 'cancelled')

    def test_full_events_offer_the_waitlist_until_the_cutoff(self):
        event = self.make_event(capacity=1)
        RSVP.objects.create(event=event, user=self.host, status=RSVP.Status.GOING)
        self.assertEqual(self.state(event)['state'], 'join_waitlist')
        soon = self.make_event(capacity=1, hours_away=0.25)
        RSVP.objects.create(event=soon, user=self.host, status=RSVP.Status.GOING)
        self.assertEqual(self.state(soon)['state'], 'full')

    def test_your_own_rsvp_wins(self):
        event = self.make_event()
        RSVP.objects.create(event=event, user=self.user, status=RSVP.Status.WAITLISTED, waitlist_position=3)
        self.assertEqual(self.state(event), {'state': 'waitlisted', 'position': 3})

    def test_who_cannot_rsvp_yet(self):
        from django.contrib.auth.models import AnonymousUser
        event = self.make_event(visibility=Event.Visibility.CAMPUS_ONLY)
        self.assertEqual(self.state(event, AnonymousUser())['state'], 'guest')
        self.assertEqual(self.state(event, self.make_user('a', is_email_verified=False))['state'], 'unverified')
        self.assertEqual(self.state(event, self.make_user('b', is_campus_verified=False))['state'], 'campus_required')

    def test_button_renders_on_the_profile(self):
        event = self.make_event()
        RSVP.objects.create(event=event, user=self.user, status=RSVP.Status.GOING)
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Cancel RSVP')
        self.assertContains(response, reverse('rsvp', args=[event.pk]))
