import re
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.accounts.selectors import get_preferences
from apps.attendance.models import CheckIn
from apps.engagement.models import EventSave
from apps.events.models import Event
from apps.interests.models import Interest, UserInterest
from apps.organizations.models import Organization, OrganizationFollow
from apps.organizations.services import follow_organization
from apps.rsvps.models import RSVP

PASSWORD = 'Strong-Pass-123'


class AccountPageTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sam', email='sam@example.edu', password=PASSWORD)
        Profile.objects.create(user=self.user, display_name='Sam')
        self.host = User.objects.create_user(username='host', email='host@example.edu', password=PASSWORD)
        self.organization = Organization.objects.create(
            name='Test Club', slug='test-club', org_type=Organization.OrgType.RSO, created_by=self.host
        )
        self.client.force_login(self.user)

    def make_event(self, slug, *, days=3):
        start = timezone.now() + timedelta(days=days)
        return Event.objects.create(
            slug=slug, title=slug.title(), host_user=self.host, organization=self.organization,
            start_at=start, end_at=start + timedelta(hours=1), location_text='Room 1', status=Event.Status.PUBLISHED,
        )


class ProfilePageTests(AccountPageTestCase):
    def test_guests_are_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_dashboard_shows_real_activity(self):
        going = self.make_event('going')
        waitlisted = self.make_event('waiting')
        saved = self.make_event('saved')
        past = self.make_event('past', days=-5)
        RSVP.objects.create(event=going, user=self.user, status=RSVP.Status.GOING)
        RSVP.objects.create(event=waitlisted, user=self.user, status=RSVP.Status.WAITLISTED, waitlist_position=2)
        RSVP.objects.create(event=past, user=self.user, status=RSVP.Status.GOING)
        CheckIn.objects.create(event=past, user=self.user, method=CheckIn.Method.MANUAL)
        EventSave.objects.create(event=saved, user=self.user)
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Waitlist #2')
        self.assertEqual(response.context['attended_count'], 1)
        self.assertEqual(len(response.context['tickets']), 2)
        self.assertEqual(response.context['saved_events'], [saved])

    def test_every_tab_opens(self):
        for tab in ['overview', 'tickets', 'saved', 'following', 'hosting', 'past', 'made-up']:
            self.assertEqual(self.client.get(reverse('profile'), {'tab': tab}).status_code, 200)

    def test_accounts_without_a_profile_can_open_the_pages(self):
        for name in ['profile', 'edit_profile', 'preferences', 'account_preferences', 'onboarding_interests']:
            Profile.objects.filter(user=self.user).delete()
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_removing_a_saved_event_only_affects_your_own(self):
        event = self.make_event('saved')
        EventSave.objects.create(event=event, user=self.user)
        EventSave.objects.create(event=event, user=self.host)
        self.client.post(reverse('remove_from_saved', args=[event.pk]), {'next': reverse('profile')})
        self.assertEqual(list(EventSave.objects.values_list('user', flat=True)), [self.host.pk])


class SidebarTests(AccountPageTestCase):
    def sidebar(self, url):
        html = self.client.get(url).content.decode()
        aside = re.search(r'<aside class="sidebar">.*?</aside>', html, re.S).group(0)
        return re.sub(r' class="active"( aria-current="page")?', '', aside)

    def test_every_signed_in_page_has_the_dashboard_sidebar(self):
        dashboard = self.sidebar(reverse('dashboard'))
        self.assertNotIn('Preferences', dashboard)
        for name in ['profile', 'edit_profile', 'preferences', 'account_preferences', 'change_password']:
            self.assertEqual(self.sidebar(reverse(name)), dashboard, name)


class EditProfileTests(AccountPageTestCase):
    def test_saving_updates_the_profile(self):
        response = self.client.post(reverse('edit_profile'), {
            'display_name': 'Sam L', 'bio': 'Hi', 'major': 'Math', 'graduation_year': '',
        })
        self.assertRedirects(response, reverse('profile'))
        profile = Profile.objects.get(user=self.user)
        self.assertEqual((profile.display_name, profile.bio, profile.major), ('Sam L', 'Hi', 'Math'))
        self.assertIsNone(profile.graduation_year)

    def test_invalid_values_show_errors_and_save_nothing(self):
        long_bio = 'x' * 501
        response = self.client.post(reverse('edit_profile'), {
            'display_name': '', 'bio': long_bio, 'major': '', 'graduation_year': '1900',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context['form'].errors), {'display_name', 'bio', 'graduation_year'})
        self.assertContains(response, long_bio)
        self.assertEqual(Profile.objects.get(user=self.user).display_name, 'Sam')


class FeedPreferencesTests(AccountPageTestCase):
    def setUp(self):
        super().setUp()
        self.interests = [Interest.objects.create(name=f'Test {n}', slug=f'test-{n}') for n in range(4)]

    def post(self, interests, **extra):
        data = {'interests': [i.pk for i in interests], 'default_tab': 'for_you', **extra}
        return self.client.post(reverse('preferences'), data)

    def test_saving_replaces_interests_and_stores_settings(self):
        UserInterest.objects.create(user=self.user, interest=self.interests[3], source=UserInterest.Source.ONBOARDING)
        response = self.post(self.interests[:3], default_tab='following', free_only='on', rsvp_app='on')
        self.assertRedirects(response, reverse('preferences'))
        saved = UserInterest.objects.filter(user=self.user)
        self.assertEqual({row.interest for row in saved}, set(self.interests[:3]))
        self.assertEqual({row.source for row in saved}, {UserInterest.Source.SETTINGS})
        preferences = get_preferences(Profile.objects.get(user=self.user))
        self.assertEqual(preferences['feed'], {'default_tab': 'following', 'free_only': True})
        self.assertEqual(preferences['notifications']['rsvp'], {'app': True, 'email': False})
        self.assertEqual(preferences['notifications']['reminders'], {'app': False, 'email': False})

    def test_fewer_than_three_interests_saves_nothing_and_keeps_choices(self):
        response = self.post(self.interests[:2], free_only='on')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pick at least 3 interests to save.')
        self.assertEqual(response.context['selected_ids'], {i.pk for i in self.interests[:2]})
        self.assertTrue(response.context['free_only'])
        self.assertFalse(UserInterest.objects.filter(user=self.user).exists())
        self.assertEqual(Profile.objects.get(user=self.user).notification_prefs, {})

    def test_defaults_turn_new_event_emails_off(self):
        response = self.client.get(reverse('preferences'))
        rows = {row['key']: row for row in response.context['notifications']}
        self.assertTrue(rows['rsvp']['email'])
        self.assertFalse(rows['new_events']['email'])


class AccountPreferencesTests(AccountPageTestCase):
    def test_saving_location_settings_keeps_other_preferences(self):
        Profile.objects.filter(user=self.user).update(notification_prefs={'feed': {'free_only': True}})
        response = self.client.post(reverse('account_preferences'), {
            'use': 'off', 'show_heat_map': 'on', 'default_map_view': 'list',
        })
        self.assertRedirects(response, reverse('account_preferences'))
        preferences = get_preferences(Profile.objects.get(user=self.user))
        self.assertEqual(preferences['location'], {
            'use': 'off', 'start_with_walk': False, 'show_heat_map': True, 'default_map_view': 'list',
        })
        self.assertTrue(preferences['feed']['free_only'])

    def test_invalid_choice_saves_nothing(self):
        response = self.client.post(reverse('account_preferences'), {'use': 'always', 'default_map_view': 'map'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Profile.objects.get(user=self.user).notification_prefs, {})

    def test_changing_password_keeps_you_signed_in(self):
        response = self.client.post(reverse('change_password'), {
            'old_password': PASSWORD, 'new_password1': 'Brand-New-Pass-456', 'new_password2': 'Brand-New-Pass-456',
        })
        self.assertRedirects(response, reverse('account_preferences'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-New-Pass-456'))
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)

    def test_wrong_current_password_is_rejected(self):
        response = self.client.post(reverse('change_password'), {
            'old_password': 'wrong', 'new_password1': 'Brand-New-Pass-456', 'new_password2': 'Brand-New-Pass-456',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))


class FollowActionTests(AccountPageTestCase):
    def post(self, action):
        url = reverse('update_followed_organization', args=[self.organization.slug])
        return self.client.post(url, {'action': action, 'next': reverse('preferences')})

    def test_mute_and_unmute_keep_the_follow_and_return_to_the_page(self):
        follow_organization(user=self.user, organization=self.organization, source='landing')
        self.assertRedirects(self.post('mute'), reverse('preferences'))
        self.assertFalse(OrganizationFollow.objects.get(user=self.user).notify)
        self.post('unmute')
        self.assertTrue(OrganizationFollow.objects.get(user=self.user).notify)

    def test_unfollow_removes_the_follow_and_lowers_the_count(self):
        follow_organization(user=self.user, organization=self.organization, source='landing')
        self.post('unfollow')
        self.assertFalse(OrganizationFollow.objects.filter(user=self.user).exists())
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.follower_count, 0)

    def test_users_cannot_change_a_follow_they_do_not_have(self):
        follow_organization(user=self.host, organization=self.organization, source='landing')
        self.assertEqual(self.post('unfollow').status_code, 404)
        self.assertTrue(OrganizationFollow.objects.filter(user=self.host).exists())

    def test_get_cannot_change_a_follow(self):
        follow_organization(user=self.user, organization=self.organization, source='landing')
        url = reverse('update_followed_organization', args=[self.organization.slug])
        self.assertEqual(self.client.get(url).status_code, 405)
