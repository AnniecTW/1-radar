import io
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.events.models import Event
from apps.events.tests.test_my_events import HostTestCase
from apps.interests.models import Interest
from apps.notifications.models import Notification
from apps.organizations.models import Organization, OrganizationMembership
from apps.rsvps.models import RSVP

MEDIA = tempfile.mkdtemp()
# Keep test uploads on disk even when the Supabase Storage keys are in .env.
LOCAL_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(MEDIA_ROOT=MEDIA, STORAGES=LOCAL_STORAGES)
class EventFormTests(HostTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.tech = Interest.objects.create(name='Robots', slug='robots-test', is_active=True)
        self.day = (timezone.localdate() + timedelta(days=10)).isoformat()

    def data(self, **overrides):
        data = {
            'host': 'me', 'title': 'Robot Battle Night', 'description': 'Build a bot, then battle it.',
            'interests': [self.tech.pk], 'date': self.day, 'start_time': '19:00', 'end_time': '21:00',
            'location_text': 'Siebel 1404', 'latitude': '40.1138', 'longitude': '-88.2249',
            'kind': 'rsvp', 'capacity': '40', 'waitlist_enabled': 'on', 'visibility': 'public', 'action': 'publish',
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    def create(self, **overrides):
        return self.client.post(reverse('create_event'), self.data(**overrides))

    def test_needs_a_campus_email(self):
        self.host.is_campus_verified = False
        self.host.save()
        response = self.client.get(reverse('create_event'))
        self.assertContains(response, 'Verify your campus email to host events')
        self.assertNotContains(response, 'name="title"')

    def test_publish_creates_a_live_event_with_pin_and_categories(self):
        response = self.create()
        event = Event.objects.get(title='Robot Battle Night')
        self.assertRedirects(response, reverse('event_detail', args=[event.slug]), fetch_redirect_response=False)
        self.assertEqual((event.status, event.capacity, event.host_user), (Event.Status.PUBLISHED, 40, self.host))
        self.assertAlmostEqual(event.location.y, 40.1138)
        self.assertEqual(list(event.interests.all()), [self.tech])
        self.assertEqual(timezone.localtime(event.start_at).hour, 19)

    def test_save_draft_needs_almost_nothing(self):
        response = self.create(action='save', description='', interests=None, date='', location_text='', latitude=None, longitude=None)
        event = Event.objects.get(title='Robot Battle Night')
        self.assertEqual(event.status, Event.Status.DRAFT)
        self.assertRedirects(response, reverse('edit_event', args=[event.pk]), fetch_redirect_response=False)

    def test_publishing_with_gaps_keeps_a_draft_and_shows_what_is_missing(self):
        response = self.create(interests=None, location_text='', latitude=None, longitude=None)
        self.assertContains(response, 'Draft saved. Fill in the highlighted fields to publish.')
        self.assertContains(response, 'Pick at least one category')
        self.assertContains(response, 'Choose a building or describe where it is.')
        self.assertEqual(Event.objects.get(title='Robot Battle Night').status, Event.Status.DRAFT)

    def test_end_must_be_after_start(self):
        response = self.create(end_time='18:00')
        self.assertContains(response, 'The end time must be after the start time.')
        self.assertFalse(Event.objects.filter(status=Event.Status.PUBLISHED).exists())

    def test_paid_events_need_a_price_and_a_ticket_link_or_contact(self):
        response = self.create(kind='paid', price_text='')
        self.assertContains(response, 'Add a price.')
        self.assertContains(response, 'Add a ticket link or a contact.')
        self.create(kind='paid', title='Gala', price_text='$20', external_url='tickets.example.com')
        gala = Event.objects.get(title='Gala')
        self.assertEqual((gala.is_free, gala.capacity, gala.external_url), (False, None, 'https://tickets.example.com'))

    def test_org_admins_post_as_their_org_and_others_cannot(self):
        org = Organization.objects.create(name='Robotics', slug='robotics-test', org_type=Organization.OrgType.RSO, created_by=self.make_user('owner'))
        stranger_org = Organization.objects.create(name='Chess', slug='chess-test', org_type=Organization.OrgType.RSO, created_by=self.make_user('chess'))
        OrganizationMembership.objects.create(organization=org, user=self.host, role=OrganizationMembership.Role.ADMIN)
        self.create(host='robotics-test')
        self.assertEqual(Event.objects.get(title='Robot Battle Night').organization, org)
        response = self.create(host=stranger_org.slug, title='Sneaky')
        self.assertContains(response, 'Select a valid choice')
        self.assertFalse(Event.objects.filter(title='Sneaky').exists())

    def test_cover_upload(self):
        buffer = io.BytesIO()
        Image.new('RGB', (40, 20), 'orange').save(buffer, 'PNG')
        upload = SimpleUploadedFile('cover.png', buffer.getvalue(), content_type='image/png')
        self.client.post(reverse('create_event'), {**self.data(), 'cover': upload})
        self.assertIn('event_covers/', Event.objects.get(title='Robot Battle Night').cover_image)

    def test_a_failed_image_upload_shows_a_message_instead_of_crashing(self):
        from unittest import mock
        buffer = io.BytesIO()
        Image.new('RGB', (40, 20), 'orange').save(buffer, 'PNG')
        upload = SimpleUploadedFile('cover.png', buffer.getvalue(), content_type='image/png')
        with mock.patch('apps.events.views._save_cover', side_effect=ValueError('Invalid endpoint')), self.assertLogs('apps.events.views', 'ERROR'):
            response = self.client.post(reverse('create_event'), {**self.data(), 'cover': upload})
        self.assertContains(response, 'be uploaded right now. Save without it')

    def test_a_chosen_photo_survives_a_mistake_and_is_saved_next_time(self):
        buffer = io.BytesIO()
        Image.new('RGB', (40, 20), 'orange').save(buffer, 'PNG')
        upload = SimpleUploadedFile('cover.png', buffer.getvalue(), content_type='image/png')
        response = self.client.post(reverse('create_event'), {**self.data(end_time='18:00'), 'cover': upload})
        self.assertContains(response, 'Your new image is kept')
        token = response.context['pending_cover']['token']
        self.client.post(reverse('create_event'), {**self.data(), 'pending_cover': token})
        self.assertIn('event_covers/', Event.objects.get(title='Robot Battle Night').cover_image)

    def test_a_forged_pending_photo_is_ignored(self):
        self.client.post(reverse('create_event'), {**self.data(), 'pending_cover': 'https://evil.example.com/x.png'})
        self.assertEqual(Event.objects.get(title='Robot Battle Night').cover_image, '')

    def test_sidebar_and_my_events_link_here(self):
        self.assertContains(self.client.get(reverse('create_event')), f'class="active" aria-current="page" href="{reverse("create_event")}"')
        self.assertContains(self.client.get(reverse('my_events')), reverse('create_event'))


@override_settings(MEDIA_ROOT=MEDIA, STORAGES=LOCAL_STORAGES)
class EditEventTests(EventFormTests):
    def test_edit_a_draft_then_publish_it(self):
        draft = self.make_event('Half Done', status=Event.Status.DRAFT)
        self.assertContains(self.client.get(reverse('edit_event', args=[draft.pk])), 'value="Half Done"')
        self.client.post(reverse('edit_event', args=[draft.pk]), self.data(title='All Done'))
        draft.refresh_from_db()
        self.assertEqual((draft.title, draft.status), ('All Done', Event.Status.PUBLISHED))

    def test_moving_a_published_event_tells_attendees(self):
        self.create()
        event = Event.objects.get(title='Robot Battle Night')
        RSVP.objects.create(event=event, user=self.make_user('sam'), status=RSVP.Status.GOING)
        response = self.client.post(reverse('edit_event', args=[event.pk]), self.data(start_time='18:00', action='save'))
        self.assertRedirects(response, reverse('my_events'), fetch_redirect_response=False)
        self.assertTrue(Notification.objects.filter(event=event, type=Notification.Type.EVENT_UPDATED).exists())

    def test_capacity_cannot_drop_below_people_going(self):
        self.create()
        event = Event.objects.get(title='Robot Battle Night')
        for name in ('a1', 'a2'):
            RSVP.objects.create(event=event, user=self.make_user(name), status=RSVP.Status.GOING)
        response = self.client.post(reverse('edit_event', args=[event.pk]), self.data(capacity='1', action='save'))
        self.assertContains(response, 'capacity cannot be lower than 2')

    def test_others_and_started_events_cannot_be_edited(self):
        other = self.make_event('Theirs', host=self.make_user('other'))
        self.assertEqual(self.client.get(reverse('edit_event', args=[other.pk])).status_code, 404)
        started = self.make_event('Started', hours_away=-1)
        self.assertRedirects(self.client.get(reverse('edit_event', args=[started.pk])), reverse('my_events'), fetch_redirect_response=False)

    def test_host_cannot_be_changed_on_edit(self):
        draft = self.make_event('Mine', status=Event.Status.DRAFT)
        org = Organization.objects.create(name='Robotics', slug='robotics-test', org_type=Organization.OrgType.RSO, created_by=self.host)
        self.client.post(reverse('edit_event', args=[draft.pk]), self.data(host=org.slug, action='save'))
        draft.refresh_from_db()
        self.assertIsNone(draft.organization)
