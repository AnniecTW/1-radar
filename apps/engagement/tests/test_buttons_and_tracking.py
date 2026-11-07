from django.urls import reverse

from apps.engagement.models import EventLike, EventOutboundClick, EventSave, EventView
from apps.engagement.services import guess_view_source
from apps.events.models import Event
from apps.events.tests.test_my_events import HostTestCase
from apps.organizations.models import Organization, OrganizationFollow

JSON = {'HTTP_ACCEPT': 'application/json'}


class EngagementTestCase(HostTestCase):
    def setUp(self):
        super().setUp()
        self.fan = self.make_user('fan')
        self.event = self.make_event('Robotics Night')
        self.client.force_login(self.fan)


class SaveAndLikeTests(EngagementTestCase):
    def test_save_and_unsave(self):
        response = self.client.post(reverse('save_event', args=[self.event.pk]), {'saved': '1'}, **JSON)
        self.assertEqual(response.json(), {'active': True})
        self.client.post(reverse('save_event', args=[self.event.pk]), {'saved': '1'}, **JSON)
        self.assertEqual(EventSave.objects.filter(user=self.fan).count(), 1)
        self.client.post(reverse('save_event', args=[self.event.pk]), {'saved': '0'}, **JSON)
        self.assertFalse(EventSave.objects.exists())

    def test_saved_events_show_on_the_profile(self):
        self.client.post(reverse('save_event', args=[self.event.pk]), {'saved': '1', 'next': '/accounts/profile/'})
        self.assertContains(self.client.get(reverse('profile') + '?tab=saved'), 'Robotics Night')

    def test_like_returns_the_new_count(self):
        response = self.client.post(reverse('like_event', args=[self.event.pk]), {'liked': '1'}, **JSON)
        self.assertEqual(response.json(), {'active': True, 'count': 1})
        response = self.client.post(reverse('like_event', args=[self.event.pk]), {'liked': '0'}, **JSON)
        self.assertEqual(response.json(), {'active': False, 'count': 0})

    def test_guests_are_sent_to_sign_in_and_back(self):
        self.client.logout()
        response = self.client.post(reverse('save_event', args=[self.event.pk]), {'saved': '1', 'next': '/events/robotics-night/'})
        self.assertIn(reverse('login'), response.url)
        self.assertIn('next=%2Fevents%2Frobotics-night%2F', response.url)
        self.assertEqual(self.client.post(reverse('like_event', args=[self.event.pk]), {'liked': '1'}, **JSON).status_code, 401)
        self.assertFalse(EventSave.objects.exists() or EventLike.objects.exists())

    def test_drafts_cannot_be_saved(self):
        draft = self.make_event('Secret', status=Event.Status.DRAFT)
        self.assertEqual(self.client.post(reverse('save_event', args=[draft.pk]), {'saved': '1'}).status_code, 404)

    def test_event_page_shows_the_buttons_in_their_current_state(self):
        EventSave.objects.create(user=self.fan, event=self.event)
        response = self.client.get(reverse('event_detail', args=[self.event.slug]))
        self.assertContains(response, reverse('save_event', args=[self.event.pk]))
        self.assertContains(response, 'data-label-on="Saved"')
        self.assertContains(response, '<span data-engage-label>Saved</span>', html=False)


class FollowTests(EngagementTestCase):
    def setUp(self):
        super().setUp()
        self.org = Organization.objects.create(name='Robotics', slug='robotics-test', org_type=Organization.OrgType.RSO, created_by=self.host)

    def test_follow_and_unfollow_keep_the_count(self):
        url = reverse('follow_organization', args=[self.org.slug])
        self.assertEqual(self.client.post(url, {'following': '1', 'source': 'event_page'}, **JSON).json(), {'active': True, 'count': 1})
        self.assertEqual(OrganizationFollow.objects.get(user=self.fan).source, 'event_page')
        self.assertEqual(self.client.post(url, {'following': '0'}, **JSON).json(), {'active': False, 'count': 0})

    def test_org_page_and_event_page_show_follow(self):
        self.event.organization = self.org
        self.event.save()
        self.assertContains(self.client.get(reverse('show_organization_profile', args=[self.org.slug])), 'data-label-off="Follow"')
        self.assertContains(self.client.get(reverse('event_detail', args=[self.event.slug])), reverse('follow_organization', args=[self.org.slug]))


class TrackingTests(EngagementTestCase):
    def test_a_visit_is_counted_once_per_half_hour_with_its_source(self):
        url = reverse('event_detail', args=[self.event.slug])
        self.client.get(url, HTTP_REFERER='http://testserver/explore/?date=all')
        self.client.get(url)
        view = EventView.objects.get(event=self.event)
        self.assertEqual((view.user, view.source), (self.fan, 'map'))

    def test_guests_are_counted_by_session(self):
        self.client.logout()
        self.client.get(reverse('event_detail', args=[self.event.slug]))
        view = EventView.objects.get(event=self.event)
        self.assertIsNone(view.user)
        self.assertTrue(view.session_key)

    def test_hosts_viewing_their_own_event_are_not_counted(self):
        self.client.force_login(self.host)
        self.client.get(reverse('event_detail', args=[self.event.slug]))
        self.assertFalse(EventView.objects.exists())

    def test_sources(self):
        cases = {'': 'direct', 'http://other.site/': 'direct', 'http://testserver/': 'feed', 'http://testserver/?q=robots': 'search',
                 'http://testserver/organizations/robotics/': 'org_page', 'http://testserver/explore/': 'map'}
        for referer, source in cases.items():
            self.assertEqual(guess_view_source(referer, 'testserver'), source, referer)

    def test_ticket_clicks_are_counted_then_sent_to_the_host_site(self):
        paid = self.make_event('Gala', is_free=False, price_text='$20', external_url='https://tickets.example.com/gala')
        response = self.client.get(reverse('event_tickets', args=[paid.pk]))
        self.assertRedirects(response, 'https://tickets.example.com/gala', fetch_redirect_response=False)
        self.assertEqual(EventOutboundClick.objects.get(event=paid).kind, 'tickets_link')
        self.assertEqual(self.client.get(reverse('event_tickets', args=[self.event.pk])).status_code, 404)

    def test_analytics_shows_the_tracked_numbers(self):
        self.client.get(reverse('event_detail', args=[self.event.slug]))
        self.client.post(reverse('save_event', args=[self.event.pk]), {'saved': '1'})
        self.client.force_login(self.host)
        kpis = {k['label']: k['value'] for k in self.client.get(reverse('event_analytics', args=[self.event.pk])).context['kpis']}
        self.assertEqual((kpis['Views'], kpis['Saves']), (1, 1))
