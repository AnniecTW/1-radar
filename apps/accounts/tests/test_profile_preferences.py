from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Profile, User
from apps.interests.models import Interest, UserInterest
from apps.organizations.models import Organization, OrganizationFollow
from apps.organizations.services import follow_organization


class AccountPageTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sam', email='sam@example.edu', password='Strong-Pass-123')
        Profile.objects.create(user=self.user, display_name='Sam')
        self.client.force_login(self.user)


class ProfilePageTests(AccountPageTestCase):
    def test_guests_are_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_saving_updates_the_profile(self):
        response = self.client.post(reverse('profile'), {
            'display_name': 'Sam L', 'bio': 'Hi', 'major': 'Math', 'graduation_year': '',
        })
        self.assertRedirects(response, reverse('profile'))
        profile = Profile.objects.get(user=self.user)
        self.assertEqual((profile.display_name, profile.bio, profile.major), ('Sam L', 'Hi', 'Math'))
        self.assertIsNone(profile.graduation_year)

    def test_invalid_values_show_errors_and_save_nothing(self):
        long_bio = 'x' * 501
        response = self.client.post(reverse('profile'), {
            'display_name': '', 'bio': long_bio, 'major': '', 'graduation_year': '1900',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context['form'].errors), {'display_name', 'bio', 'graduation_year'})
        self.assertContains(response, long_bio)
        self.assertEqual(Profile.objects.get(user=self.user).display_name, 'Sam')

    def test_accounts_without_a_profile_can_open_the_page(self):
        Profile.objects.filter(user=self.user).delete()
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_accounts_without_a_profile_can_open_onboarding(self):
        Profile.objects.filter(user=self.user).delete()
        self.assertEqual(self.client.get(reverse('onboarding_interests')).status_code, 200)


class PreferencesPageTests(AccountPageTestCase):
    def setUp(self):
        super().setUp()
        self.tech = Interest.objects.create(name='Test Tech', slug='test-tech')
        self.art = Interest.objects.create(name='Test Art', slug='test-art')
        self.host = User.objects.create_user(username='host', email='host@example.edu', password='Strong-Pass-123')
        self.organization = Organization.objects.create(
            name='Test Club', slug='test-club', org_type=Organization.OrgType.RSO, created_by=self.host
        )

    def test_saving_interests_replaces_old_picks(self):
        UserInterest.objects.create(user=self.user, interest=self.tech, source=UserInterest.Source.ONBOARDING)
        response = self.client.post(reverse('preferences'), {'interests': [self.art.pk]})
        self.assertRedirects(response, reverse('preferences'))
        saved = UserInterest.objects.get(user=self.user)
        self.assertEqual((saved.interest, saved.source), (self.art, UserInterest.Source.SETTINGS))

    def test_interests_can_be_cleared(self):
        UserInterest.objects.create(user=self.user, interest=self.tech, source=UserInterest.Source.ONBOARDING)
        self.client.post(reverse('preferences'), {})
        self.assertFalse(UserInterest.objects.filter(user=self.user).exists())

    def _post_follow_action(self, action):
        url = reverse('update_followed_organization', args=[self.organization.slug])
        return self.client.post(url, {'action': action})

    def test_mute_and_unmute_keep_the_follow(self):
        follow_organization(user=self.user, organization=self.organization, source='landing')
        self._post_follow_action('mute')
        self.assertFalse(OrganizationFollow.objects.get(user=self.user).notify)
        self._post_follow_action('unmute')
        self.assertTrue(OrganizationFollow.objects.get(user=self.user).notify)

    def test_unfollow_removes_the_follow_and_lowers_the_count(self):
        follow_organization(user=self.user, organization=self.organization, source='landing')
        self._post_follow_action('unfollow')
        self.assertFalse(OrganizationFollow.objects.filter(user=self.user).exists())
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.follower_count, 0)

    def test_users_cannot_change_a_follow_they_do_not_have(self):
        follow_organization(user=self.host, organization=self.organization, source='landing')
        self.assertEqual(self._post_follow_action('unfollow').status_code, 404)
        self.assertTrue(OrganizationFollow.objects.filter(user=self.host).exists())

    def test_get_cannot_change_a_follow(self):
        follow_organization(user=self.user, organization=self.organization, source='landing')
        url = reverse('update_followed_organization', args=[self.organization.slug])
        self.assertEqual(self.client.get(url).status_code, 405)
