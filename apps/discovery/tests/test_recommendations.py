"""Recommendations end to end: ranking, exclusions, fallbacks, impressions, clicks and shared location."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.discovery.models import RecommendationImpression
from apps.discovery.recommendations import (
    ALGORITHM_VERSION, FALLBACK_ALGORITHM_VERSION, LOCATION_COOKIE, prune_impressions, recommend_events,
)
from apps.engagement.models import EventSave, EventView
from apps.events.management.commands.seed_mock_data import Command as SeedMockData
from apps.events.semantic_search import DIMENSIONS, EmbeddingError
from apps.events.tests.test_my_events import HostTestCase
from apps.interests.admin import InterestAdminForm
from apps.interests.descriptions import DESCRIPTIONS
from apps.interests.models import Interest, UserInterest
from apps.organizations.models import Organization, OrganizationFollow
from apps.rsvps.models import RSVP

CAMPUS = (40.1020, -88.2272)


def vector(*hot):
    """A 384-number vector pointing along the given dimensions, standing in for a real BGE embedding."""
    values = [0.0] * DIMENSIONS
    for index in hot:
        values[index] = 1.0
    return values


MUSIC, FOOD, SPORTS = vector(0), vector(1), vector(2)


class RecommendationTestCase(HostTestCase):
    def setUp(self):
        # Never call Cloudflare from tests: embedding signals fail closed and leave vectors empty.
        patcher = patch('apps.events.semantic_search.embed_text', side_effect=EmbeddingError('offline'))
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()
        self.fan = self.make_user('fan')
        self.client.force_login(self.fan)
        self.music = Interest.objects.get(slug='music')
        self.food = Interest.objects.get(slug='food')
        self.now = timezone.now()

    def make_vector_event(self, title, embedding, *, interests=(), **fields):
        event = self.make_event(title, **fields)
        if interests:
            event.interests.add(*interests)
        type(event).objects.filter(pk=event.pk).update(embedding=embedding)
        return event

    def titles(self, events):
        return [event.title for event in events]


class RankingTests(RecommendationTestCase):
    def test_ranks_events_like_the_ones_the_user_engaged_with(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        RSVP.objects.create(event=jazz, user=self.fan, status=RSVP.Status.GOING)
        self.make_vector_event('Soccer Final', SPORTS)
        self.make_vector_event('Open Mic', MUSIC)

        events = recommend_events(self.fan, self.now)
        self.assertEqual(self.titles(events)[0], 'Open Mic')
        self.assertEqual(events[0].recommendation_algorithm, ALGORITHM_VERSION)
        self.assertEqual(events[0].recommendation_reason, 'Similar to Jazz Night')

    def test_chosen_interests_alone_give_recommendations(self):
        Interest.objects.filter(pk=self.music.pk).update(embedding=MUSIC)
        UserInterest.objects.create(user=self.fan, interest=self.music, source=UserInterest.Source.ONBOARDING)
        self.make_vector_event('Soccer Final', SPORTS)
        self.make_vector_event('Open Mic', MUSIC, interests=[self.music])

        events = recommend_events(self.fan, self.now)
        self.assertEqual(self.titles(events), ['Open Mic', 'Soccer Final'])
        self.assertEqual(events[0].recommendation_reason, 'Because you like Music')

    def test_leaves_out_events_already_in_hand_hosted_or_dismissed(self):
        EventSave.objects.create(user=self.fan, event=self.make_vector_event('Saved', MUSIC))
        RSVP.objects.create(user=self.fan, event=self.make_vector_event('Going', MUSIC), status=RSVP.Status.GOING)
        RSVP.objects.create(user=self.fan, event=self.make_vector_event('Cancelled', MUSIC),
                            status=RSVP.Status.CANCELLED)
        self.make_vector_event('Fan Hosts This', MUSIC, host=self.fan)
        dismissed = self.make_vector_event('Dismissed', MUSIC)
        RecommendationImpression.objects.create(user=self.fan, event=dismissed, rank=1, score=0,
                                                algorithm_version=ALGORITHM_VERSION, dismissed=True)

        self.assertEqual(self.titles(recommend_events(self.fan, self.now)), ['Cancelled'])

    def test_followed_host_and_nearby_events_rank_higher(self):
        club = Organization.objects.create(name='Robotics Club', slug='robotics-club-rec',
                                           org_type=Organization.OrgType.RSO, created_by=self.host)
        OrganizationFollow.objects.create(user=self.fan, organization=club, source=OrganizationFollow.Source.ORG_PAGE)
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        EventSave.objects.create(user=self.fan, event=jazz)
        far = self.make_vector_event('Far Concert', MUSIC, location=Point(-88.30, 40.20, srid=4326))
        near = self.make_vector_event('Near Concert', MUSIC, location=Point(CAMPUS[1], CAMPUS[0], srid=4326))
        followed = self.make_vector_event('Club Concert', MUSIC, organization=club)

        self.assertEqual(recommend_events(self.fan, self.now)[0], followed)
        with_location = recommend_events(self.fan, self.now, location=CAMPUS)
        self.assertLess(with_location.index(near), with_location.index(far))
        self.assertEqual(next(e for e in with_location if e == near).recommendation_reason, 'Similar to Jazz Night')

    def test_falls_back_to_interest_tags_when_nothing_has_a_vector(self):
        UserInterest.objects.create(user=self.fan, interest=self.food, source=UserInterest.Source.ONBOARDING)
        food_fair = self.make_event('Food Fair')
        food_fair.interests.add(self.food)
        self.make_event('Chess Club')

        events = recommend_events(self.fan, self.now)
        self.assertEqual(self.titles(events), ['Food Fair'])
        self.assertEqual(events[0].recommendation_algorithm, FALLBACK_ALGORITHM_VERSION)

    def test_nothing_to_go_on_means_no_recommendations(self):
        self.make_vector_event('Open Mic', MUSIC)
        self.assertEqual(recommend_events(self.fan, self.now), [])


class HomePageTests(RecommendationTestCase):
    def test_prompt_to_pick_interests_when_there_is_nothing_to_recommend(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Pick a few interests to get recommendations.')
        self.assertContains(response, reverse('preferences'))

    def test_guests_see_no_recommended_row(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('dashboard')), 'Recommended for you')

    def test_impressions_are_logged_and_clicks_marked(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        EventSave.objects.create(user=self.fan, event=jazz)
        open_mic = self.make_vector_event('Open Mic', MUSIC)

        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Similar to Jazz Night')
        self.assertContains(response, reverse('event_detail', args=[open_mic.slug]) + '?ref=rec')
        impression = RecommendationImpression.objects.get(user=self.fan, event=open_mic)
        self.assertEqual((impression.rank, impression.algorithm_version, impression.clicked),
                         (1, ALGORITHM_VERSION, False))

        self.client.get(reverse('event_detail', args=[open_mic.slug]) + '?ref=rec')
        impression.refresh_from_db()
        self.assertTrue(impression.clicked)
        self.assertEqual(EventView.objects.get(event=open_mic, user=self.fan).source, 'recommendation')


class PruneImpressionTests(RecommendationTestCase):
    def impression(self, event, days_ago, user=None, **fields):
        row = RecommendationImpression.objects.create(
            user=user or self.fan, event=event, rank=1, score=0.5, algorithm_version=ALGORITHM_VERSION, **fields)
        # shown_at is set automatically on create, so backdate it afterwards.
        RecommendationImpression.objects.filter(pk=row.pk).update(shown_at=self.now - timedelta(days=days_ago))
        return row.pk

    def remaining(self, *pks):
        return set(RecommendationImpression.objects.filter(pk__in=pks).values_list('pk', flat=True))

    def test_rows_older_than_six_months_go_except_dismissals_of_upcoming_events(self):
        past = self.make_event('Last Spring', hours_away=-24 * 200)
        upcoming = self.make_event('Next Week')
        old = self.impression(past, 181)
        old_clicked = self.impression(past, 181, clicked=True)
        old_dismissed_past = self.impression(past, 181, dismissed=True)
        old_dismissed_upcoming = self.impression(upcoming, 181, dismissed=True)
        recent = self.impression(past, 179)

        self.assertEqual(prune_impressions(self.now), 3)
        self.assertEqual(self.remaining(old, old_clicked, old_dismissed_past, old_dismissed_upcoming, recent),
                         {old_dismissed_upcoming, recent})

    def test_home_page_prunes_only_the_visitors_rows(self):
        event = self.make_event('Last Spring', hours_away=-24 * 200)
        mine = self.impression(event, 200)
        theirs = self.impression(event, 200, user=self.make_user('other'))
        self.client.get(reverse('dashboard'))
        self.assertEqual(self.remaining(mine, theirs), {theirs})

    def test_command_prunes_everyone(self):
        event = self.make_event('Last Spring', hours_away=-24 * 200)
        rows = [self.impression(event, 200), self.impression(event, 200, user=self.make_user('other')),
                self.impression(event, 20)]
        out = StringIO()
        call_command('prune_recommendation_impressions', stdout=out)
        self.assertIn('Deleted 2 impressions older than 180 days', out.getvalue())
        call_command('prune_recommendation_impressions', '--days', '10', stdout=StringIO())
        self.assertEqual(self.remaining(*rows), set())


class LocationTests(RecommendationTestCase):
    url = reverse('set_recommendation_location')

    def test_location_is_kept_approximate_in_a_cookie_and_the_row_comes_back(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        EventSave.objects.create(user=self.fan, event=jazz)
        self.make_vector_event('Open Mic', MUSIC, location=Point(CAMPUS[1], CAMPUS[0], srid=4326))

        response = self.client.post(self.url, {'lat': '40.1023456', 'lng': '-88.2271234'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['location'], {'lat': 40.1, 'lng': -88.225})  # The ~500 m grid.
        self.assertIn('Open Mic', response.json()['html'])
        self.assertNotIn('data-location-banner', response.json()['html'])
        self.assertIn(LOCATION_COOKIE, response.cookies)
        self.assertTrue(response.cookies[LOCATION_COOKIE]['httponly'])
        # The home page now ranks with it and doesn't ask again.
        self.assertNotContains(self.client.get(reverse('dashboard')), 'data-location-banner')

    def test_quiet_refresh_replaces_the_impressions_the_page_just_logged(self):
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        EventSave.objects.create(user=self.fan, event=jazz)
        open_mic = self.make_vector_event('Open Mic', MUSIC)
        self.client.get(reverse('dashboard'))
        self.client.post(self.url, {'lat': '40.102', 'lng': '-88.227', 'replace': '1'})
        self.assertEqual(RecommendationImpression.objects.filter(user=self.fan, event=open_mic).count(), 1)
        # Sharing on purpose, later, is a second real showing and is counted.
        self.client.post(self.url, {'lat': '40.102', 'lng': '-88.227'})
        self.assertEqual(RecommendationImpression.objects.filter(user=self.fan, event=open_mic).count(), 2)

    def test_bad_coordinates_and_guests_are_refused(self):
        self.assertEqual(self.client.post(self.url, {'lat': 'north'}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {'lat': '91', 'lng': '0'}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {'lat': 'nan', 'lng': '0'}).status_code, 400)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, {'lat': '40', 'lng': '-88'}).status_code, 302)

    def test_banner_shows_until_a_location_is_shared(self):
        self.assertContains(self.client.get(reverse('dashboard')), 'data-location-banner')

    def test_use_my_location_button_waits_in_the_row_until_a_location_is_shared(self):
        # The button is hidden in the HTML; landing-location.js reveals it after "Not now" or a browser block.
        jazz = self.make_vector_event('Jazz Night', MUSIC, hours_away=-72)
        EventSave.objects.create(user=self.fan, event=jazz)
        self.make_vector_event('Open Mic', MUSIC)
        home = self.client.get(reverse('dashboard'))
        self.assertContains(home, 'data-location-share aria-describedby="use-location-hint" hidden')
        self.assertContains(home, 'so Recommended for you can put events near you first.')  # Its hover hint.
        self.client.post(self.url, {'lat': '40.102', 'lng': '-88.227'})
        self.assertNotContains(self.client.get(reverse('dashboard')), 'data-location-share')
        self.client.post(reverse('turn_off_recommendation_location'))
        self.client.cookies.pop(LOCATION_COOKIE, None)
        self.assertNotContains(self.client.get(reverse('dashboard')), 'data-location-share')

    def test_map_heading_says_it_is_centered_on_campus_until_a_location_is_shared(self):
        not_shared = 'Radar doesn’t have your location, so the map is centered on campus.'
        self.assertContains(self.client.get(reverse('dashboard')), not_shared)
        self.client.post(self.url, {'lat': '40.102', 'lng': '-88.227'})
        self.assertNotContains(self.client.get(reverse('dashboard')), 'data-map-hint')
        self.client.post(reverse('turn_off_recommendation_location'))
        self.client.cookies.pop(LOCATION_COOKIE, None)
        self.assertContains(self.client.get(reverse('dashboard')), 'Location is off in Account &amp; privacy')
        self.client.logout()
        self.assertContains(self.client.get(reverse('dashboard')), not_shared)

    def test_dont_use_my_location_hides_the_banner_and_forgets_the_cookie(self):
        self.client.post(self.url, {'lat': '40.102', 'lng': '-88.227'})
        shared_cookie = self.client.cookies[LOCATION_COOKIE].value
        response = self.client.post(reverse('account_preferences'), {'use': 'off', 'default_map_view': 'map'})
        self.assertEqual(response.cookies[LOCATION_COOKIE].value, '')  # Deleted straight away.

        self.client.cookies[LOCATION_COOKIE] = shared_cookie  # Even if the browser still sends it...
        home = self.client.get(reverse('dashboard'))
        self.assertNotContains(home, 'data-location-banner')
        self.assertContains(home, '<script id="user-location" type="application/json">null</script>', html=False)
        self.assertEqual(home.cookies[LOCATION_COOKIE].value, '')  # ...it is ignored and deleted.
        self.assertEqual(self.client.post(self.url, {'lat': '40.102', 'lng': '-88.227'}).status_code, 403)

    def test_dont_ask_again_turns_location_off_in_account_and_privacy(self):
        response = self.client.post(reverse('turn_off_recommendation_location'))
        self.assertEqual(response.json(), {'location': 'off'})
        self.assertContains(self.client.get(reverse('account_preferences')), 'value="off" checked')
        self.assertNotContains(self.client.get(reverse('dashboard')), 'data-location-banner')

    def test_the_removed_remember_option_counts_as_while_using_radar(self):
        from apps.accounts.selectors import get_preferences
        from apps.accounts.services import get_or_create_profile

        profile = get_or_create_profile(self.fan)
        profile.notification_prefs = {'location': {'use': 'save'}}
        profile.save()
        self.assertEqual(get_preferences(profile)['location']['use'], 'session')
        self.assertContains(self.client.get(reverse('dashboard')), 'data-location-banner')


class ExploreMapLocationTests(RecommendationTestCase):
    """Share once, used everywhere, and "Don't use my location" greys out the map's location controls."""

    def explore(self, **params):
        return self.client.get(reverse('explore_map'), params)

    def test_the_map_opens_on_a_location_shared_on_the_home_page(self):
        self.client.post(reverse('set_recommendation_location'), {'lat': '40.1023', 'lng': '-88.2271'})
        response = self.explore()
        self.assertContains(response, '<script id="shared-location" type="application/json">[40.1, -88.225]</script>',
                            html=False)
        self.assertContains(response, f'shareUrl:"{reverse("share_location")}"')

    def test_sharing_from_the_map_is_used_by_recommendations(self):
        response = self.client.post(reverse('share_location'), {'lat': '40.1023', 'lng': '-88.2271'})
        self.assertEqual(response.json(), {'location': {'lat': 40.1, 'lng': -88.225}})
        self.assertNotContains(self.client.get(reverse('dashboard')), 'data-location-banner')
        self.assertEqual(self.client.post(reverse('share_location'), {'lat': 'north'}).status_code, 400)

    def test_location_off_greys_out_the_crosshair_and_walk_filter(self):
        self.client.post(reverse('turn_off_recommendation_location'))
        response = self.explore(walk='1')
        self.assertContains(response, 'data-map-locate aria-disabled="true"')
        self.assertContains(response, '<input type="checkbox" name="walk" value="1" disabled>', html=False)
        self.assertContains(response, reverse('account_preferences'))
        self.assertContains(response, 'walk:false')
        self.assertContains(response, 'shareUrl:""')
        self.assertEqual(self.client.post(reverse('share_location'), {'lat': '40.1', 'lng': '-88.2'}).status_code, 403)

    def test_the_walk_filter_snaps_the_coordinates_it_is_sent(self):
        # (40.1024, -88.2276) snaps to (40.100, -88.230). This event is about 1.22 km south of the snapped
        # point, inside the 1.25 km walk, but about 1.5 km from the raw one.
        self.make_event('South Quad Picnic', location=Point(-88.230, 40.089, srid=4326))
        response = self.client.get(reverse('map_events'), {
            'bbox': '-88.4,39.9,-88.0,40.3', 'date': 'all', 'walk': '1', 'lat': '40.1024', 'lng': '-88.2276'})
        self.assertEqual([event['title'] for event in response.json()['events']], ['South Quad Picnic'])

    def test_guests_keep_the_map_controls_but_share_nothing(self):
        self.client.logout()
        response = self.explore()
        self.assertContains(response, '<button type="button" data-map-locate aria-label="Show my location">', html=False)
        self.assertContains(response, 'shareUrl:""')


class InterestEmbeddingTests(RecommendationTestCase):
    def test_saving_an_interest_never_calls_cloudflare_during_tests(self):
        with patch('apps.events.semantic_search.embed_text', return_value=FOOD) as embed:
            Interest.objects.create(name='Baking', slug='baking', description='Baking: bake-offs')
        embed.assert_not_called()

    @override_settings(INTEREST_AUTO_EMBED=True)
    def test_new_and_reworded_interests_are_embedded_from_their_description(self):
        with patch('apps.events.semantic_search.embed_text', return_value=FOOD) as embed:
            interest = Interest.objects.create(name='Baking', slug='baking', group='Social',
                                               description='Baking: bake-offs, cake decorating')
            embed.assert_called_once_with('Baking: bake-offs, cake decorating')
            interest.is_active = False
            interest.save()
            self.assertEqual(embed.call_count, 1)  # Nothing the model reads changed.
            interest.description = 'Baking: bread classes'
            interest.save()
            self.assertEqual(embed.call_count, 2)
        interest.refresh_from_db()
        self.assertEqual(list(interest.embedding), FOOD)

    def test_command_fills_in_missing_vectors(self):
        self.assertTrue(Interest.objects.get(slug='music').description.startswith('Music: concerts'))
        with patch('apps.events.semantic_search.embed_text', return_value=MUSIC):
            call_command('embed_interests', stdout=StringIO())
        self.assertFalse(Interest.objects.filter(is_active=True, embedding__isnull=True).exists())

    def test_admin_form_requires_a_description(self):
        form = InterestAdminForm(data={'name': 'Baking', 'slug': 'baking', 'group': 'Social', 'is_active': True})
        self.assertFalse(form.is_valid())
        self.assertIn('description', form.errors)
        self.assertNotIn('embedding', form.fields)

    def test_seed_fills_blank_descriptions_but_keeps_edited_ones(self):
        Interest.objects.filter(slug='music').update(description='')
        Interest.objects.filter(slug='food').update(description='Food: edited by an admin')
        demo = Interest.objects.create(name='Demo Technology', slug='demo-technology', group='Academic')
        SeedMockData(stdout=StringIO())._fill_interest_descriptions()
        self.assertEqual(Interest.objects.get(slug='music').description, DESCRIPTIONS['music'])
        self.assertEqual(Interest.objects.get(slug='food').description, 'Food: edited by an admin')
        demo.refresh_from_db()
        self.assertTrue(demo.description.startswith('Demo Technology: coding workshops'))
