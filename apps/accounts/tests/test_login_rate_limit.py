from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import LOGIN_FAILURES_PER_EMAIL, LOGIN_FAILURES_PER_IP

PASSWORD = 'Correct-Pass-123'


class LoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse('login')
        User.objects.create_user(username='sam', email='sam@example.edu', password=PASSWORD)

    def attempt(self, email='sam@example.edu', password='wrong-password', **extra):
        return self.client.post(self.url, {'email': email, 'password': password}, **extra)

    def fail_times(self, count, email='sam@example.edu'):
        for _ in range(count):
            self.assertEqual(self.attempt(email).status_code, 200)

    def test_locks_after_too_many_failures_even_for_correct_password(self):
        self.fail_times(LOGIN_FAILURES_PER_EMAIL)
        response = self.attempt(password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Too many failed sign-in attempts', status_code=429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_success_before_the_limit_resets_the_count(self):
        self.fail_times(LOGIN_FAILURES_PER_EMAIL - 1)
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)
        self.client.logout()
        self.fail_times(LOGIN_FAILURES_PER_EMAIL - 1)
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)

    def test_unknown_email_is_limited_the_same_way(self):
        self.fail_times(LOGIN_FAILURES_PER_EMAIL, email='ghost@example.edu')
        self.assertEqual(self.attempt(email='ghost@example.edu').status_code, 429)

    def test_lock_on_one_email_does_not_block_another(self):
        self.fail_times(LOGIN_FAILURES_PER_EMAIL)
        User.objects.create_user(username='kim', email='kim@example.edu', password=PASSWORD)
        self.assertEqual(self.attempt(email='kim@example.edu', password=PASSWORD).status_code, 302)

    def test_ip_limit_blocks_spraying_across_emails(self):
        for number in range(LOGIN_FAILURES_PER_IP):
            self.attempt(email=f'user{number}@example.edu')
        self.assertEqual(self.attempt(email='another@example.edu').status_code, 429)
