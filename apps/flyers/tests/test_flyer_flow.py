import json
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Event
from apps.events.tests.test_my_events import HostTestCase
from apps.flyers.extraction import ExtractionError
from apps.flyers.models import FlyerUpload
from apps.flyers.tests.test_extraction import png_bytes
from apps.interests.models import Interest
from apps.venues.models import Venue

MEDIA = tempfile.mkdtemp()
LOCAL_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
CALL_MODEL = 'apps.flyers.services.call_vision_model'


def flyer_file(name='flyer.png'):
    return SimpleUploadedFile(name, png_bytes().read(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA, STORAGES=LOCAL_STORAGES)
class SnapAFlyerTests(HostTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.tech, _ = Interest.objects.get_or_create(name='Tech', defaults={'slug': 'tech-flyer-test'})
        self.siebel = Venue.objects.create(name='Siebel Center for Computer Science',
                                           location=Point(-88.2249, 40.1138, srid=4326))
        self.day = timezone.localdate() + timedelta(days=10)
        self.answer = json.dumps({
            'title': 'Robot Battle Night', 'description': 'Build a bot, then battle it.',
            'date': f'{self.day:%b} {self.day.day}', 'start_time': '7 PM', 'end_time': '9 PM',
            'location': 'Room 1404, Siebel Center for Computer Science', 'organizer': None,
            'price': 'Free', 'registration_url': None, 'categories': ['tech'],
        })

    def upload(self, answer=None, side_effect=None, file=None):
        with mock.patch(CALL_MODEL, return_value=answer or self.answer, side_effect=side_effect):
            return self.client.post(reverse('upload_flyer'), {'flyer': file or flyer_file()})

    def test_create_event_page_offers_snap_a_flyer(self):
        self.assertContains(self.client.get(reverse('create_event')), reverse('upload_flyer'))

    def test_hosting_needs_a_campus_email(self):
        self.host.is_campus_verified = False
        self.host.save()
        response = self.upload()
        self.assertContains(response, 'Verify your campus email to host events')
        self.assertFalse(FlyerUpload.objects.exists())

    def test_a_read_flyer_prefills_the_form_for_review(self):
        response = self.upload()
        flyer = FlyerUpload.objects.get()
        self.assertRedirects(response, f"{reverse('create_event')}?flyer={flyer.pk}", fetch_redirect_response=False)
        self.assertEqual(flyer.status, FlyerUpload.Status.SUCCEEDED)
        self.assertTrue(flyer.image.endswith('.jpg'))
        self.assertIsNotNone(flyer.latency_ms)

        page = self.client.get(response['Location'])
        self.assertContains(page, 'value="Robot Battle Night"')
        self.assertContains(page, f'value="{self.day.isoformat()}"')
        self.assertContains(page, 'value="19:00')
        self.assertContains(page, 'value="Room 1404"')
        self.assertContains(page, f'name="flyer" value="{flyer.pk}"')
        self.assertContains(page, 'We filled this in from your flyer')
        self.assertContains(page, flyer.image)  # shown beside the form and attached as the cover

    def test_fields_the_flyer_lacks_are_highlighted(self):
        self.upload(answer=json.dumps({'title': 'Open Mic', 'date': f'{self.day:%b} {self.day.day}'}))
        page = self.client.get(f"{reverse('create_event')}?flyer={FlyerUpload.objects.get().pk}")
        review = json.loads(page.content.decode().split('id="flyer-review" type="application/json">')[1].split('<')[0])
        self.assertEqual(review['start_time'], 'missing')
        self.assertEqual(review['location_text'], 'missing')

    def test_a_failed_read_falls_back_to_the_form_with_the_flyer_as_cover(self):
        response = self.upload(side_effect=ExtractionError('The flyer reader is unavailable right now.'))
        flyer = FlyerUpload.objects.get()
        self.assertEqual(flyer.status, FlyerUpload.Status.FAILED)
        self.assertEqual(flyer.error_message, 'The flyer reader is unavailable right now.')
        page = self.client.get(response['Location'])
        self.assertContains(page, "We couldn&#x27;t read this flyer")
        self.assertContains(page, flyer.image)
        self.assertNotContains(page, 'value="Robot Battle Night"')

    def test_json_the_model_garbles_counts_as_a_failed_read(self):
        self.upload(answer='Sorry, I cannot read this image.')
        self.assertEqual(FlyerUpload.objects.get().status, FlyerUpload.Status.FAILED)

    def test_rejects_files_that_are_not_images(self):
        fake = SimpleUploadedFile('flyer.png', b'not really a png', content_type='image/png')
        with mock.patch(CALL_MODEL) as call:
            response = self.client.post(reverse('upload_flyer'), {'flyer': fake})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Upload a JPG, PNG or WebP', status_code=400)
        call.assert_not_called()
        self.assertFalse(FlyerUpload.objects.exists())

    @override_settings(FLYER_DAILY_LIMIT=1)
    def test_daily_limit(self):
        self.upload()
        response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'the daily limit', status_code=400)
        self.assertEqual(FlyerUpload.objects.count(), 1)

    def test_publishing_links_the_event_and_counts_edits(self):
        self.upload()
        flyer = FlyerUpload.objects.get()
        response = self.client.post(f"{reverse('create_event')}?flyer={flyer.pk}", {
            'flyer': str(flyer.pk), 'host': 'me', 'title': 'Robot Battle Royale',  # the host changed the title
            'description': 'Build a bot, then battle it.', 'interests': [self.tech.pk],
            'date': self.day.isoformat(), 'start_time': '19:00', 'end_time': '21:00',
            'venue': self.siebel.pk, 'location_text': 'Room 1404', 'latitude': '40.1138', 'longitude': '-88.2249',
            'kind': 'rsvp', 'waitlist_enabled': 'on', 'visibility': 'public', 'action': 'publish',
            'pending_cover': self.client.get(f"{reverse('create_event')}?flyer={flyer.pk}").context['pending_cover']['token'],
        })
        event = Event.objects.get()
        self.assertRedirects(response, reverse('event_detail', args=[event.slug]), fetch_redirect_response=False)
        flyer.refresh_from_db()
        self.assertEqual((event.status, event.source), (Event.Status.PUBLISHED, Event.Source.FLYER_AI))
        self.assertEqual(event.cover_image, flyer.image)
        self.assertEqual((flyer.event, flyer.fields_edited_count), (event, 1))

    def test_someone_elses_flyer_is_ignored(self):
        self.upload()
        flyer = FlyerUpload.objects.get()
        self.client.force_login(self.make_user('other'))
        page = self.client.get(f"{reverse('create_event')}?flyer={flyer.pk}")
        self.assertNotContains(page, 'value="Robot Battle Night"')
        self.assertNotContains(page, flyer.image)
