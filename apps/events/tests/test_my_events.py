from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event, EventCheckInStaff
from apps.notifications.models import Notification
from apps.organizations.models import Organization, OrganizationMembership
from apps.rsvps.models import RSVP


class HostTestCase(TestCase):
    def setUp(self):
        self.host = self.make_user('host')
        self.client.force_login(self.host)

    def make_user(self, name):
        return User.objects.create_user(
            username=name, email=f'{name}@example.edu', password='Strong-Pass-123',
            is_email_verified=True, is_campus_verified=True,
        )

    def make_event(self, title, *, hours_away=48, status=Event.Status.PUBLISHED, host=None, **fields):
        start = timezone.now() + timedelta(hours=hours_away)
        defaults = {'start_at': start, 'end_at': start + timedelta(hours=2), 'location_text': 'Siebel 1404'}
        if status != Event.Status.DRAFT:
            defaults['slug'] = title.lower().replace(' ', '-')
        return Event.objects.create(title=title, host_user=host or self.host, status=status, **{**defaults, **fields})

    def tab(self, name, **params):
        return self.client.get(reverse('my_events'), {'tab': name, **params})


class MyEventsTests(HostTestCase):
    def test_needs_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('my_events')).status_code, 302)

    def test_each_tab_shows_its_events(self):
        self.make_event('Robotics Night')
        draft = self.make_event('Winter Showcase', status=Event.Status.DRAFT, location_text='')
        self.make_event('Hack Night', hours_away=-30)
        self.make_event('Soldering 101', status=Event.Status.CANCELLED)
        self.make_event('Someone Else', host=self.make_user('other'))

        upcoming = self.tab('upcoming')
        self.assertContains(upcoming, 'Robotics Night')
        self.assertNotContains(upcoming, 'Hack Night')
        self.assertNotContains(upcoming, 'Someone Else')

        drafts = self.tab('drafts')
        self.assertContains(drafts, 'Winter Showcase')
        self.assertContains(drafts, 'location')
        self.assertNotContains(drafts, reverse('publish_draft_event', args=[draft.pk]))

        past = self.tab('past')
        self.assertContains(past, 'Hack Night')
        self.assertContains(past, 'Soldering 101')

    def test_org_admins_see_org_events_and_can_filter_them_out(self):
        org = Organization.objects.create(name='Robotics Club', slug='robotics-club', org_type=Organization.OrgType.RSO, created_by=self.make_user('owner'))
        OrganizationMembership.objects.create(organization=org, user=self.host, role=OrganizationMembership.Role.ADMIN)
        self.make_event('Club Meeting', organization=org, host=org.created_by)
        self.make_event('My Own Thing')
        self.assertContains(self.tab('upcoming'), 'Club Meeting')
        only_me = self.tab('upcoming', host='me')
        self.assertNotContains(only_me, 'Club Meeting')
        self.assertContains(only_me, 'My Own Thing')

    def test_checkin_staff_see_assigned_events_without_host_controls(self):
        owner = self.make_user('owner')
        org = Organization.objects.create(name='Volleyball', slug='volleyball', org_type=Organization.OrgType.RSO, created_by=owner)
        event = self.make_event('Home Game', organization=org, host=owner)
        EventCheckInStaff.objects.create(event=event, user=self.host, assigned_by=owner)
        self.assertNotContains(self.tab('upcoming'), 'Home Game')
        staff = self.tab('staff')
        self.assertContains(staff, 'Home Game')
        self.assertNotContains(staff, 'Cancel event')
        self.assertNotContains(staff, reverse('event_analytics', args=[event.pk]))

    def test_next_up_spotlights_the_soonest_event_with_its_photo(self):
        self.make_event('Later Thing', hours_away=200)
        self.make_event('Soon Thing', hours_away=30, cover_image='https://example.com/soon.jpg')
        response = self.tab('past')
        self.assertEqual(response.context['next_up'].title, 'Soon Thing')
        self.assertContains(response, 'src="https://example.com/soon.jpg"')

    def test_no_spotlight_without_upcoming_events(self):
        self.make_event('Old', hours_away=-30)
        self.assertNotContains(self.tab('upcoming'), 'class="next-up"')

    def test_sidebar_links_here(self):
        self.assertContains(self.tab('upcoming'), f'class="active" aria-current="page" href="{reverse("my_events")}"')


class HostActionTests(HostTestCase):
    def test_host_cancels_and_attendees_are_notified(self):
        event = self.make_event('Robotics Night')
        RSVP.objects.create(event=event, user=self.make_user('sam'), status=RSVP.Status.GOING)
        self.client.post(reverse('cancel_hosted_event', args=[event.pk]), {'reason': 'Room flooded'})
        event.refresh_from_db()
        self.assertEqual((event.status, event.cancel_reason), (Event.Status.CANCELLED, 'Room flooded'))
        self.assertTrue(Notification.objects.filter(event=event, type=Notification.Type.EVENT_CANCELLED).exists())

    def test_others_cannot_cancel(self):
        event = self.make_event('Robotics Night', host=self.make_user('other'))
        response = self.client.post(reverse('cancel_hosted_event', args=[event.pk]))
        self.assertRedirects(response, reverse('my_events'), fetch_redirect_response=False)
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.PUBLISHED)

    def test_publish_a_ready_draft(self):
        draft = self.make_event('Winter Showcase', status=Event.Status.DRAFT)
        self.assertContains(self.tab('drafts'), 'Ready to publish')
        self.client.post(reverse('publish_draft_event', args=[draft.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, Event.Status.PUBLISHED)
        self.assertTrue(draft.slug)

    def test_an_incomplete_draft_stays_a_draft(self):
        draft = self.make_event('', status=Event.Status.DRAFT)
        self.client.post(reverse('publish_draft_event', args=[draft.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, Event.Status.DRAFT)

    def test_get_is_not_allowed(self):
        event = self.make_event('Robotics Night')
        self.assertEqual(self.client.get(reverse('cancel_hosted_event', args=[event.pk])).status_code, 405)
