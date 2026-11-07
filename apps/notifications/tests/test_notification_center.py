from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event
from apps.notifications.models import Notification
from apps.notifications.selectors import count_unread_notifications

PASSWORD = 'Strong-Pass-123'


class NotificationCenterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sam', email='sam@example.edu', password=PASSWORD)
        self.other = User.objects.create_user(username='kim', email='kim@example.edu', password=PASSWORD)
        start = timezone.now() + timedelta(days=2)
        self.event = Event.objects.create(
            slug='chess-night', title='Chess Night', host_user=self.other, start_at=start,
            end_at=start + timedelta(hours=1), location_text='Room 1', status=Event.Status.PUBLISHED,
        )
        self.client.force_login(self.user)

    def make(self, type, user=None, **extra):
        return Notification.objects.create(user=user or self.user, type=type, event=self.event, **extra)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('list_notifications')).status_code, 302)

    def test_list_shows_own_notifications_only_with_messages(self):
        self.make(Notification.Type.RSVP_CONFIRMED)
        self.make(Notification.Type.WAITLIST_JOINED, payload={'position': 4})
        self.make(Notification.Type.EVENT_CANCELLED, payload={'reason': 'Snow day'})
        self.make(Notification.Type.RSVP_CONFIRMED, user=self.other)
        response = self.client.get(reverse('list_notifications'))
        self.assertContains(response, "You're going to Chess Night", count=1)
        self.assertContains(response, 'Your position is 4.')
        self.assertContains(response, 'Snow day')
        self.assertEqual(len(response.context['rows']), 3)

    def test_bell_badge_counts_unread(self):
        self.make(Notification.Type.RSVP_CONFIRMED)
        self.make(Notification.Type.RSVP_CONFIRMED, user=self.other)
        self.assertContains(self.client.get(reverse('list_notifications')), '1 unread')

    def test_open_marks_read_and_redirects_to_event(self):
        notification = self.make(Notification.Type.RSVP_CONFIRMED)
        response = self.client.post(reverse('open_notification', args=[notification.pk]))
        self.assertRedirects(response, reverse('event_detail', args=['chess-night']), fetch_redirect_response=False)
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)
        self.assertEqual(count_unread_notifications(self.user), 0)

    def test_cannot_open_someone_elses_notification(self):
        theirs = self.make(Notification.Type.RSVP_CONFIRMED, user=self.other)
        response = self.client.post(reverse('open_notification', args=[theirs.pk]))
        self.assertRedirects(response, reverse('list_notifications'))
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_open_requires_post(self):
        notification = self.make(Notification.Type.RSVP_CONFIRMED)
        self.assertEqual(self.client.get(reverse('open_notification', args=[notification.pk])).status_code, 405)

    def test_mark_all_read_only_touches_own(self):
        self.make(Notification.Type.RSVP_CONFIRMED)
        theirs = self.make(Notification.Type.RSVP_CONFIRMED, user=self.other)
        self.client.post(reverse('read_all_notifications'))
        self.assertEqual(count_unread_notifications(self.user), 0)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_unread_filter(self):
        read = self.make(Notification.Type.RSVP_CONFIRMED, read_at=timezone.now())
        self.make(Notification.Type.WAITLIST_CLOSED)
        rows = self.client.get(reverse('list_notifications') + '?filter=unread').context['rows']
        self.assertEqual([row['notification'].pk for row in rows if row['notification'].pk == read.pk], [])
        self.assertEqual(len(rows), 1)

    def test_bell_badge_shows_on_every_signed_in_page(self):
        self.make(Notification.Type.RSVP_CONFIRMED)
        self.make(Notification.Type.WAITLIST_CLOSED)
        pages = {
            'discover': reverse('dashboard'),
            'explore map': reverse('explore_map'),
            'profile': reverse('profile'),
            'preferences': reverse('preferences'),
            'my events': reverse('my_events'),
            'event detail': reverse('event_detail', args=['chess-night']),
            'notifications': reverse('list_notifications'),
        }
        for name, url in pages.items():
            with self.subTest(page=name):
                response = self.client.get(url)
                self.assertContains(response, 'bell-badge')
                self.assertContains(response, '2 unread')

    def test_no_badge_when_everything_is_read(self):
        self.make(Notification.Type.RSVP_CONFIRMED, read_at=timezone.now())
        self.assertNotContains(self.client.get(reverse('dashboard')), 'bell-badge')
