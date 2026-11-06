from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.analytics.selectors import build_checkin_buckets, build_funnel
from apps.attendance.models import CheckIn
from apps.engagement.models import EventSave, EventView
from apps.events.models import Event
from apps.events.tests.test_my_events import HostTestCase
from apps.organizations.models import Organization, OrganizationMembership
from apps.rsvps.models import RSVP


class EventAnalyticsPageTests(HostTestCase):
    def setUp(self):
        super().setUp()
        self.event = self.make_event('Hack Night', hours_away=-1, end_at=timezone.now() + timedelta(hours=1))
        self.alice, self.bob = self.make_user('alice'), self.make_user('bob')
        for user in (self.alice, self.bob):
            RSVP.objects.create(event=self.event, user=user, status=RSVP.Status.GOING)
        CheckIn.objects.create(event=self.event, user=self.alice, method=CheckIn.Method.MANUAL)
        EventView.objects.create(event=self.event, user=self.alice, source='map')
        EventSave.objects.create(event=self.event, user=self.alice)

    def page(self, event=None):
        return self.client.get(reverse('event_analytics', args=[(event or self.event).pk]))

    def test_host_sees_the_numbers(self):
        response = self.page()
        self.assertEqual(response.status_code, 200)
        kpis = {k['label']: k['value'] for k in response.context['kpis']}
        self.assertEqual((kpis['Views'], kpis['Saves'], kpis['RSVPs'], kpis['Check-ins']), (1, 1, 2, 1))
        self.assertEqual(kpis['Attendance rate'], '50%')
        self.assertEqual(kpis['No-show rate'], '—')
        self.assertContains(response, 'Export attendee CSV')
        self.assertEqual([s['label'] for s in response.context['sources']], ['Map'])

    def test_others_get_not_found(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.page().status_code, 404)
        self.assertEqual(self.client.get(reverse('export_attendee_csv', args=[self.event.pk])).status_code, 404)

    def test_org_admins_see_analytics_but_only_owners_export(self):
        owner = self.make_user('owner')
        org = Organization.objects.create(name='Robotics Club', slug='robotics-club', org_type=Organization.OrgType.RSO, created_by=owner)
        admin = self.make_user('admin')
        OrganizationMembership.objects.create(organization=org, user=admin, role=OrganizationMembership.Role.ADMIN)
        event = self.make_event('Club Night', organization=org, host=owner)
        self.client.force_login(admin)
        response = self.page(event)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Export attendee CSV')
        self.assertEqual(self.client.get(reverse('export_attendee_csv', args=[event.pk])).status_code, 404)

    def test_csv_lists_going_attendees_and_defuses_formulas(self):
        Profile.objects.update_or_create(user=self.bob, defaults={'display_name': '=HYPERLINK("x")'})
        response = self.client.get(reverse('export_attendee_csv', args=[self.event.pk]))
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        body = response.content.decode()
        self.assertIn('alice@example.edu', body)
        self.assertIn("'=HYPERLINK", body)
        self.assertIn('Yes', body)

    def test_drop_in_and_paid_events_render(self):
        drop_in = self.make_event('Pickup Volleyball', rsvp_required=False)
        paid = self.make_event('Gala', is_free=False, price_text='$20', external_url='https://tickets.example.com')
        self.assertContains(self.page(drop_in), 'Interested taps')
        self.assertContains(self.page(paid), 'Ticket link clicks')

    def test_my_events_links_to_analytics(self):
        self.assertContains(self.tab('upcoming'), reverse('event_analytics', args=[self.event.pk]))


class ChartMathTests(HostTestCase):
    def test_funnel_shares_of_views_and_sqrt_widths(self):
        funnel = build_funnel([('Views', 100), ('Saved', 25), ('RSVP', 36), ('Checked in', 0)])
        self.assertEqual([s['width'] for s in funnel], [100, 50, 60, 0])
        self.assertEqual([s['share'] for s in funnel], [None, 25, 36, 0])

    def test_checkins_land_in_15_minute_buckets_and_early_arrivals_count_in_the_first(self):
        event = self.make_event('Hack Night')
        times = [event.start_at - timedelta(minutes=20), event.start_at + timedelta(minutes=16), event.end_at + timedelta(minutes=5)]
        chart = build_checkin_buckets(event, times)
        counts = [b['count'] for b in chart['buckets']]
        self.assertEqual(len(counts), 8)
        self.assertEqual((counts[0], counts[1], counts[-1]), (1, 1, 1))
