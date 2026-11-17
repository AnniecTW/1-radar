import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User

OLD = 'Old-Password-123'
NEW = 'Brand-New-Pass-456'


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='sam', email='sam@example.edu', password=OLD)

    def request_link(self, email='sam@example.edu'):
        mail.outbox.clear()
        response = self.client.post(reverse('request_password_reset'), {'email': email})
        return response, (re.search(r'http\S+/password-reset/\S+/', mail.outbox[0].body).group(0) if mail.outbox else None)

    def test_login_page_links_to_forgot_password(self):
        self.assertContains(self.client.get(reverse('login')), reverse('request_password_reset'))

    def test_same_response_for_known_and_unknown_email(self):
        known, link = self.request_link()
        unknown, none_link = self.request_link('nobody@example.edu')
        self.assertIsNotNone(link)
        self.assertIsNone(none_link)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertContains(unknown, 'If an account exists')

    def test_reset_changes_password_and_link_is_single_use(self):
        _, link = self.request_link()
        self.assertContains(self.client.get(link), 'Choose a new')
        response = self.client.post(link, {'password1': NEW, 'password2': NEW})
        self.assertRedirects(response, reverse('login'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        self.assertEqual(self.client.get(link).status_code, 400)

    def test_weak_or_mismatched_password_rejected(self):
        _, link = self.request_link()
        self.assertContains(self.client.post(link, {'password1': NEW, 'password2': 'different'}), 'do not match')
        self.assertContains(self.client.post(link, {'password1': '123', 'password2': '123'}), 'field-error')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))

    def test_tampered_link_is_rejected(self):
        _, link = self.request_link()
        self.assertEqual(self.client.get(link[:-3] + 'x/').status_code, 400)

    def test_reset_signs_out_other_sessions(self):
        other = self.client_class()
        other.force_login(self.user)
        self.assertEqual(other.get(reverse('profile')).status_code, 200)
        _, link = self.request_link()
        self.client.post(link, {'password1': NEW, 'password2': NEW})
        self.assertEqual(other.get(reverse('profile')).status_code, 302)

    def test_requests_are_rate_limited_per_email(self):
        for _ in range(3):
            self.request_link()
        _, link = self.request_link()
        self.assertIsNone(link)
