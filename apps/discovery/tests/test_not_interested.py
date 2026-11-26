""""Not interested" on Recommended cards (FR-43): the penalty on similar events, cancelling the dismissed
event's own views and likes, and the dismiss / undo endpoint."""
import math
from datetime import timedelta

from django.urls import reverse

from apps.discovery.models import RecommendationImpression
from apps.discovery.recommendations import (
    ALGORITHM_VERSION, DISMISS_PENALTY, build_profile, recommend_events,
)
from apps.engagement.models import EventLike, EventSave, EventView
from apps.interests.models import UserInterest
from apps.rsvps.models import RSVP

from .test_recommendations import MUSIC, RecommendationTestCase, vector


def near_music(similarity, other):
    """A unit vector whose cosine similarity to MUSIC is `similarity`, leaning toward dimension `other`."""
    values = vector()
    values[0] = similarity
    values[other] = math.sqrt(1 - similarity ** 2)
    return values


class PenaltyTests(RecommendationTestCase):
    def setUp(self):
        super().setUp()
        # The profile points somewhere else entirely, so similarity to it doesn't muddy the comparison.
        past = self.make_vector_event('Chess Club', vector(10), hours_away=-72)
        RSVP.objects.create(event=past, user=self.fan, status=RSVP.Status.GOING)

    def dismiss(self, event, days_ago=0):
        self.client.post(reverse('dismiss_recommendation', args=[event.pk]), {'rank': '3'})
        when = self.now - timedelta(days=days_ago)
        RecommendationImpression.objects.filter(user=self.fan, event=event).update(shown_at=when, dismissed_at=when)

    def penalties(self):
        return {event.title: event.rec_penalty for event in recommend_events(self.fan, self.now)}

    def test_only_events_close_to_a_dismissed_one_lose_score(self):
        self.dismiss(self.make_vector_event('Jazz Night', MUSIC))
        self.make_vector_event('Jazz Night (next week)', MUSIC)
        self.make_vector_event('Blues Jam', near_music(0.82, 1))
        self.make_vector_event('Poetry Slam', near_music(0.5, 2))
        penalties = self.penalties()
        self.assertNotIn('Jazz Night', penalties)  # The dismissed event itself stays out of the row.
        self.assertAlmostEqual(penalties['Jazz Night (next week)'], DISMISS_PENALTY, places=3)  # A repeat: full.
        self.assertAlmostEqual(penalties['Blues Jam'], DISMISS_PENALTY * (0.82 - 0.75) / 0.15, places=3)
        self.assertEqual(penalties['Poetry Slam'], 0.0)

    def test_the_penalty_comes_off_the_score(self):
        repeat = self.make_vector_event('Jazz Night (next week)', MUSIC)
        before = {event.pk: event.rec_score for event in recommend_events(self.fan, self.now)}[repeat.pk]
        self.dismiss(self.make_vector_event('Jazz Night', MUSIC))
        ranked = {event.pk: event for event in recommend_events(self.fan, self.now)}
        self.assertAlmostEqual(before - ranked[repeat.pk].rec_score, DISMISS_PENALTY, places=3)
        self.assertEqual(ranked[repeat.pk].recommendation_algorithm, 'embedding-v2')

    def test_several_dismissals_take_the_biggest_penalty_not_the_sum(self):
        self.dismiss(self.make_vector_event('Jazz Night', MUSIC))
        self.dismiss(self.make_vector_event('Jazz Brunch', MUSIC))
        self.make_vector_event('Blues Jam', near_music(0.82, 1))
        self.assertAlmostEqual(self.penalties()['Blues Jam'], DISMISS_PENALTY * (0.82 - 0.75) / 0.15, places=3)

    def test_the_penalty_fades_with_a_30_day_half_life(self):
        self.dismiss(self.make_vector_event('Jazz Night', MUSIC, hours_away=-24 * 29), days_ago=30)
        self.make_vector_event('Jazz Night (next week)', MUSIC)
        self.assertAlmostEqual(self.penalties()['Jazz Night (next week)'], DISMISS_PENALTY / 2, places=3)

    def test_events_without_a_vector_get_no_penalty(self):
        self.dismiss(self.make_vector_event('Jazz Night', MUSIC))
        no_vector = self.make_event('New Jazz Event')
        no_vector.interests.add(self.music)
        self.make_vector_event('Filler', vector(10))
        ranked = {event.title: event for event in recommend_events(self.fan, self.now)}
        self.assertEqual(ranked['New Jazz Event'].rec_penalty, 0.0)


class CancelledSignalTests(RecommendationTestCase):
    def test_dismissing_cancels_the_events_views_and_likes(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC)
        EventView.objects.create(event=jazz, user=self.fan)
        EventLike.objects.create(event=jazz, user=self.fan)
        self.assertIsNotNone(build_profile(self.fan, self.now).vector)
        self.client.post(reverse('dismiss_recommendation', args=[jazz.pk]))
        self.assertIsNone(build_profile(self.fan, self.now).vector)

    def test_coming_back_to_the_event_after_dismissing_it_counts_again(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC)
        EventView.objects.create(event=jazz, user=self.fan)
        self.client.post(reverse('dismiss_recommendation', args=[jazz.pk]))
        self.assertIsNone(build_profile(self.fan, self.now).vector)
        EventView.objects.create(event=jazz, user=self.fan)  # Found it again in search, say.
        self.assertEqual(build_profile(self.fan, self.now).vector, MUSIC)

    def test_a_dismissal_from_before_dismissed_at_uses_the_show_time(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC)
        row = RecommendationImpression.objects.create(user=self.fan, event=jazz, rank=1, score=0.5,
                                                      algorithm_version=ALGORITHM_VERSION, dismissed=True)
        RecommendationImpression.objects.filter(pk=row.pk).update(shown_at=self.now - timedelta(hours=1))
        before = EventView.objects.create(event=jazz, user=self.fan)
        EventView.objects.filter(pk=before.pk).update(created_at=self.now - timedelta(hours=2))
        self.assertIsNone(build_profile(self.fan, self.now).vector)
        EventView.objects.create(event=jazz, user=self.fan)
        self.assertEqual(build_profile(self.fan, self.now).vector, MUSIC)

    def test_an_rsvp_from_before_the_dismissal_still_counts(self):
        # A page left open in another tab: the user RSVPs, then taps "Not interested" on the old page.
        jazz = self.make_vector_event('Jazz Night', MUSIC)
        RecommendationImpression.objects.create(user=self.fan, event=jazz, rank=1, score=0.5,
                                                algorithm_version=ALGORITHM_VERSION)
        RSVP.objects.create(event=jazz, user=self.fan, status=RSVP.Status.GOING)
        self.client.post(reverse('dismiss_recommendation', args=[jazz.pk]))
        self.assertEqual(build_profile(self.fan, self.now).vector, MUSIC)

    def test_a_save_still_counts_after_a_dismissal(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC)
        self.client.post(reverse('dismiss_recommendation', args=[jazz.pk]))
        EventSave.objects.create(event=jazz, user=self.fan)
        self.assertEqual(build_profile(self.fan, self.now).vector, MUSIC)

    def test_undo_brings_the_views_back(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC)
        EventView.objects.create(event=jazz, user=self.fan)
        url = reverse('dismiss_recommendation', args=[jazz.pk])
        self.client.post(url)
        self.client.post(url, {'undo': '1'})
        self.assertEqual(build_profile(self.fan, self.now).vector, MUSIC)


class DismissEndpointTests(RecommendationTestCase):
    def setUp(self):
        super().setUp()
        UserInterest.objects.create(user=self.fan, interest=self.music, source=UserInterest.Source.ONBOARDING)
        self.jazz = self.make_vector_event('Jazz Night', MUSIC, interests=[self.music])
        self.url = reverse('dismiss_recommendation', args=[self.jazz.pk])

    def test_marks_the_latest_showing_as_dismissed(self):
        older = RecommendationImpression.objects.create(user=self.fan, event=self.jazz, rank=2, score=0.4,
                                                        algorithm_version=ALGORITHM_VERSION)
        RecommendationImpression.objects.filter(pk=older.pk).update(shown_at=self.now - timedelta(days=2))
        latest = RecommendationImpression.objects.create(user=self.fan, event=self.jazz, rank=5, score=0.4,
                                                         algorithm_version=ALGORITHM_VERSION)
        response = self.client.post(self.url, {'rank': '5'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'dismissed': True})
        self.assertEqual(set(RecommendationImpression.objects.filter(dismissed=True)), {latest})
        latest.refresh_from_db()
        self.assertGreaterEqual(latest.dismissed_at, latest.shown_at)
        self.client.post(self.url, {'undo': '1'})
        latest.refresh_from_db()
        self.assertEqual((latest.dismissed, latest.dismissed_at), (False, None))

    def test_logs_a_row_when_the_event_was_never_logged(self):
        self.client.post(self.url, {'rank': '4'}, HTTP_ACCEPT='application/json')
        row = RecommendationImpression.objects.get(user=self.fan, event=self.jazz)
        self.assertEqual((row.dismissed, row.rank, row.score), (True, 4, 0.0))
        self.assertIsNotNone(row.dismissed_at)

    def test_the_event_leaves_the_row_and_undo_brings_it_back(self):
        self.assertIn('Jazz Night', self.titles(recommend_events(self.fan, self.now)))
        self.client.post(self.url, HTTP_ACCEPT='application/json')
        self.assertNotIn('Jazz Night', self.titles(recommend_events(self.fan, self.now)))
        response = self.client.post(self.url, {'undo': '1'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'dismissed': False})
        self.assertIn('Jazz Night', self.titles(recommend_events(self.fan, self.now)))

    def test_without_javascript_it_lands_back_on_the_home_page(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, f"{reverse('dashboard')}#recommendations", fetch_redirect_response=False)

    def test_needs_sign_in_and_a_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.assertFalse(RecommendationImpression.objects.filter(dismissed=True).exists())

    def test_only_recommended_cards_have_the_button(self):
        self.make_vector_event('Open Mic', MUSIC, interests=[self.music])
        home = self.client.get(reverse('recommendations_row'))
        shown = len(home.context['recommended'])
        self.assertGreater(shown, 0)
        self.assertContains(home, 'data-dismiss-recommendation', count=shown)
        self.assertContains(home, 'aria-label="Not interested in Jazz Night"')
