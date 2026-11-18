"""The recommendation rules that need no database: weights, decay, averaging, the category cap and reasons."""
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.discovery.recommendations import (
    LIKE_WEIGHT, LOCATION_COOKIE, MAX_VIEWS_PER_EVENT, RSVP_WEIGHT, SAVE_WEIGHT, SCORE_WEIGHTS, VIEW_WEIGHT,
    EventSignal, apply_category_cap, decay, read_location, recommendation_reason, remember_location,
    round_location, score_weights, weighted_average,
)

NOW = datetime(2026, 11, 17, 12, tzinfo=dt_timezone.utc)


def days_ago(days):
    return NOW - timedelta(days=days)


class DecayTests(SimpleTestCase):
    def test_half_life_is_thirty_days(self):
        self.assertAlmostEqual(decay(NOW, NOW), 1.0)
        self.assertAlmostEqual(decay(days_ago(30), NOW), 0.5)
        self.assertAlmostEqual(decay(days_ago(180), NOW), 1 / 64)

    def test_future_times_do_not_count_extra(self):
        self.assertAlmostEqual(decay(NOW + timedelta(days=3), NOW), 1.0)


class EventSignalTests(SimpleTestCase):
    def test_only_the_strongest_action_counts(self):
        signal = EventSignal()
        signal.add_strong(LIKE_WEIGHT, NOW, NOW)
        signal.add_strong(RSVP_WEIGHT, NOW, NOW)
        signal.add_strong(SAVE_WEIGHT, NOW, NOW)
        self.assertAlmostEqual(signal.weight(NOW), RSVP_WEIGHT)

    def test_views_are_capped_per_event(self):
        signal = EventSignal(soft_times=[NOW] * 10)
        self.assertAlmostEqual(signal.weight(NOW), VIEW_WEIGHT * MAX_VIEWS_PER_EVENT)

    def test_views_before_a_stronger_action_count_and_later_ones_do_not(self):
        signal = EventSignal(soft_times=[days_ago(5), days_ago(1)])
        signal.add_strong(SAVE_WEIGHT, days_ago(3), NOW)
        expected = SAVE_WEIGHT * decay(days_ago(3), NOW) + VIEW_WEIGHT * decay(days_ago(5), NOW)
        self.assertAlmostEqual(signal.weight(NOW), expected)

    def test_older_actions_weigh_less(self):
        recent, old = EventSignal(), EventSignal()
        recent.add_strong(RSVP_WEIGHT, days_ago(1), NOW)
        old.add_strong(RSVP_WEIGHT, days_ago(60), NOW)
        self.assertGreater(recent.weight(NOW), old.weight(NOW))
        self.assertAlmostEqual(old.weight(NOW), RSVP_WEIGHT / 4, places=1)


class WeightedAverageTests(SimpleTestCase):
    def test_the_example_from_the_plan(self):
        # Jazz Night RSVP (4), Taco Festival like (2), Basketball view (1).
        profile = weighted_average([([0.9, 0.1, 0.0], 4), ([0.2, 0.9, 0.0], 2), ([0.0, 0.1, 0.9], 1)])
        for value, expected in zip(profile, [4.0 / 7, 2.3 / 7, 0.9 / 7]):
            self.assertAlmostEqual(value, expected)

    def test_nothing_to_average(self):
        self.assertIsNone(weighted_average([]))
        self.assertIsNone(weighted_average([([1.0, 0.0], 0), (None, 3)]))


class ScoreWeightTests(SimpleTestCase):
    def test_prd_weights_with_location(self):
        self.assertEqual(score_weights(True), SCORE_WEIGHTS)

    def test_proximity_is_shared_out_without_location(self):
        weights = score_weights(False)
        self.assertEqual(weights['proximity'], 0.0)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights['similarity'], 0.45 / 0.85)


class CategoryCapTests(SimpleTestCase):
    def test_no_category_takes_more_than_four_of_ten(self):
        events = [SimpleNamespace(name=f'music-{i}', categories=['music']) for i in range(8)]
        events += [SimpleNamespace(name=f'food-{i}', categories=['food']) for i in range(8)]
        picked = apply_category_cap(events, lambda event: event.categories)
        self.assertEqual([event.name for event in picked],
                         [f'music-{i}' for i in range(4)] + [f'food-{i}' for i in range(4)]
                         + ['music-4', 'music-5'])

    def test_an_event_counts_toward_each_of_its_categories(self):
        events = [SimpleNamespace(categories=['music', 'food']) for _ in range(4)]
        events += [SimpleNamespace(categories=['food']), SimpleNamespace(categories=['tech'])]
        picked = apply_category_cap(events, lambda event: event.categories, size=5)
        self.assertEqual(picked[4].categories, ['tech'])

    def test_skipped_events_fill_the_row_rather_than_leave_gaps(self):
        events = [SimpleNamespace(categories=['music']) for _ in range(6)]
        self.assertEqual(len(apply_category_cap(events, lambda event: event.categories)), 6)


def fake_event(interests=(), organization=None, **fields):
    interest_objects = [SimpleNamespace(pk=pk, name=name) for pk, name in interests]
    return SimpleNamespace(interests=SimpleNamespace(all=lambda: interest_objects),
                           organization=organization, **fields)


class ReasonTests(SimpleTestCase):
    def test_similar_to_an_event_the_user_engaged_with(self):
        event = fake_event(interests=[(1, 'Music')])
        anchors = [('Jazz Night', [1.0, 0.0]), ('Taco Festival', [0.0, 1.0])]
        self.assertEqual(recommendation_reason(event, {1}, anchors, [0.95, 0.05]), 'Similar to Jazz Night')

    def test_chosen_interest(self):
        event = fake_event(interests=[(2, 'Food'), (1, 'Music')])
        self.assertEqual(recommendation_reason(event, {1}, [], None), 'Because you like Music')

    def test_followed_host(self):
        event = fake_event(organization=SimpleNamespace(name='Robotics Club'), rec_follows=1.0)
        self.assertEqual(recommendation_reason(event, set(), [], None), 'From Robotics Club, which you follow')

    def test_nearby_and_nothing_to_say(self):
        self.assertEqual(recommendation_reason(fake_event(rec_distance=800.0), set(), [], None),
                         'A short walk from you')
        self.assertEqual(recommendation_reason(fake_event(rec_distance=4000.0), set(), [], None), '')


class LocationCookieTests(SimpleTestCase):
    """The shared location lives in a signed cookie, never in the database."""

    def request_with_cookie(self, user_pk, location=(40.112, -88.229), at=NOW):
        sharer = RequestFactory().post('/')
        sharer.user = SimpleNamespace(pk=user_pk)
        response = HttpResponse()
        remember_location(response, sharer, location, at)
        reader = RequestFactory().get('/')
        reader.COOKIES[LOCATION_COOKIE] = response.cookies[LOCATION_COOKIE].value
        return reader, response.cookies[LOCATION_COOKIE]

    def test_snapped_to_a_grid_of_about_half_a_kilometre(self):
        self.assertEqual(round_location(40.1123456, -88.2287654), (40.11, -88.23))
        self.assertEqual(round_location(40.1026, -88.2262), (40.105, -88.225))

    def test_read_back_by_the_same_user_for_six_hours(self):
        request, cookie = self.request_with_cookie(7)
        request.user = SimpleNamespace(pk=7)
        self.assertEqual(read_location(request, NOW + timedelta(hours=5, minutes=59)), (40.112, -88.229))
        self.assertIsNone(read_location(request, NOW + timedelta(hours=6, minutes=1)))
        self.assertEqual(cookie['max-age'], 6 * 3600)
        self.assertTrue(cookie['httponly'])

    def test_another_account_on_the_same_browser_ignores_it(self):
        request, _ = self.request_with_cookie(7)
        request.user = SimpleNamespace(pk=8)
        self.assertIsNone(read_location(request, NOW))

    def test_missing_or_edited_cookies_are_ignored(self):
        request = RequestFactory().get('/')
        request.user = SimpleNamespace(pk=7)
        self.assertIsNone(read_location(request, NOW))
        request.COOKIES[LOCATION_COOKIE] = 'junk'
        self.assertIsNone(read_location(request, NOW))
        signed, _ = self.request_with_cookie(7)
        request.COOKIES[LOCATION_COOKIE] = signed.COOKIES[LOCATION_COOKIE][:-2] + 'xx'
        self.assertIsNone(read_location(request, NOW))
