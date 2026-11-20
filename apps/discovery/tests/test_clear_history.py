""""Clear recommendation history" on Account & privacy: a reset time, not a delete, with Undo for 10 minutes."""
from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.accounts.selectors import get_recommendation_reset_at
from apps.accounts.views import HISTORY_UNDO_SESSION_KEY
from apps.discovery.models import RecommendationImpression
from apps.discovery.recommendations import ALGORITHM_VERSION, DISMISS_PENALTY, build_profile, recommend_events
from apps.engagement.models import EventLike, EventSave, EventView
from apps.interests.models import UserInterest

from .test_recommendations import MUSIC, SPORTS, RecommendationTestCase, vector


class ClearHistoryTests(RecommendationTestCase):
    clear_url = reverse('clear_recommendation_history')
    undo_url = reverse('undo_clear_recommendation_history')

    def reset_at(self):
        return get_recommendation_reset_at(Profile.objects.filter(user=self.fan).first())

    def backdate(self, model, row, minutes):
        model.objects.filter(pk=row.pk).update(**{
            'shown_at' if model is RecommendationImpression else 'created_at':
                timezone.now() - timedelta(minutes=minutes)})

    def test_activity_before_the_reset_is_ignored_and_activity_after_it_counts(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC)
        soccer = self.make_vector_event('Soccer Final', SPORTS)
        self.backdate(EventView, EventView.objects.create(event=jazz, user=self.fan), 5)
        self.backdate(EventSave, EventSave.objects.create(event=jazz, user=self.fan), 5)
        self.client.post(self.clear_url)
        self.assertIsNone(build_profile(self.fan, timezone.now()).vector)
        EventLike.objects.create(event=soccer, user=self.fan)
        self.assertEqual(build_profile(self.fan, timezone.now()).vector, SPORTS)
        # Nothing was deleted.
        self.assertTrue(EventView.objects.filter(event=jazz, user=self.fan).exists())
        self.assertTrue(EventSave.objects.filter(event=jazz, user=self.fan).exists())

    def test_not_interested_events_can_come_back_and_their_penalty_goes(self):
        # The profile points elsewhere, before and after the reset, so only the penalty changes.
        EventLike.objects.create(event=self.make_vector_event('Chess Club', vector(10), hours_away=-72), user=self.fan)
        jazz = self.make_vector_event('Jazz Night', MUSIC, interests=[self.music])
        self.make_vector_event('Jazz Night (next week)', MUSIC)
        self.client.post(reverse('dismiss_recommendation', args=[jazz.pk]))
        RecommendationImpression.objects.filter(event=jazz).update(
            shown_at=timezone.now() - timedelta(minutes=5), dismissed_at=timezone.now() - timedelta(minutes=5))
        penalties = {event.title: event.rec_penalty for event in recommend_events(self.fan, timezone.now())}
        self.assertNotIn('Jazz Night', penalties)
        self.assertAlmostEqual(penalties['Jazz Night (next week)'], DISMISS_PENALTY, places=3)

        self.client.post(self.clear_url)
        EventLike.objects.create(event=self.make_vector_event('Chess Night', vector(10), hours_away=-24), user=self.fan)
        penalties = {event.title: event.rec_penalty for event in recommend_events(self.fan, timezone.now())}
        self.assertIn('Jazz Night', penalties)
        self.assertEqual(penalties['Jazz Night (next week)'], 0.0)

    def test_a_card_shown_before_the_reset_can_still_be_dismissed_after_it(self):
        UserInterest.objects.create(user=self.fan, interest=self.music, source=UserInterest.Source.ONBOARDING)
        jazz = self.make_vector_event('Jazz Night', MUSIC, interests=[self.music])
        old = RecommendationImpression.objects.create(user=self.fan, event=jazz, rank=1, score=0.5,
                                                      algorithm_version=ALGORITHM_VERSION)
        self.backdate(RecommendationImpression, old, 5)
        self.client.post(self.clear_url)
        self.assertIn('Jazz Night', self.titles(recommend_events(self.fan, timezone.now())))
        self.client.post(reverse('dismiss_recommendation', args=[jazz.pk]))  # From a page loaded before the reset.
        old.refresh_from_db()
        self.assertTrue(old.dismissed)  # Its dismissed_at is after the reset, so it counts.
        self.assertNotIn('Jazz Night', self.titles(recommend_events(self.fan, timezone.now())))

    def test_undo_puts_the_previous_reset_back(self):
        self.client.post(self.clear_url)
        first = self.reset_at()
        page = self.client.get(reverse('account_preferences'))
        self.assertContains(page, 'History cleared.')
        self.assertNotContains(page, 'data-confirm="clear-history-dialog"')

        with patch('django.utils.timezone.now', return_value=first + timedelta(minutes=1)):
            self.client.post(self.clear_url)
        self.assertGreater(self.reset_at(), first)
        response = self.client.post(self.undo_url, follow=True)
        self.assertContains(response, 'Your recommendation history is back.')
        self.assertEqual(self.reset_at(), first)  # Back to the first reset, not to no reset at all.
        local = timezone.localtime(first)
        self.assertContains(response, f'Last cleared {local:%b} {local.day}, {local.year}.')
        self.assertContains(response, 'data-confirm="clear-history-dialog"')

    def test_undo_with_no_earlier_reset_removes_it(self):
        self.client.post(self.clear_url)
        self.client.post(self.undo_url)
        self.assertIsNone(self.reset_at())

    def test_undo_expires_after_10_minutes(self):
        self.client.post(self.clear_url)
        session = self.client.session
        session[HISTORY_UNDO_SESSION_KEY]['reset_at'] = (timezone.now() - timedelta(minutes=11)).isoformat()
        session.save()
        self.assertNotContains(self.client.get(reverse('account_preferences')), 'History cleared.')
        response = self.client.post(self.undo_url, follow=True)
        self.assertContains(response, 'That can no longer be undone.')
        self.assertIsNotNone(self.reset_at())

    def test_needs_sign_in_and_a_post(self):
        self.assertEqual(self.client.get(self.clear_url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.clear_url).status_code, 302)
        self.assertIsNone(self.reset_at())
