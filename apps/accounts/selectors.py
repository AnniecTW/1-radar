from .models import CampusDomain, User


def is_email_registered(email: str) -> bool:
    return User.objects.filter(email__iexact=email.strip()).exists()


def get_campus_domain_for_email(email: str) -> CampusDomain | None:
    """Match the email's domain, or a parent domain, against active campus domains.

    A parent match lets `students.university.edu` count for `university.edu`.
    """
    domain = email.rsplit('@', 1)[-1].strip().lower()
    parts = domain.split('.')
    candidates = ['.'.join(parts[index:]) for index in range(len(parts) - 1)]
    return CampusDomain.objects.filter(domain__in=candidates, is_active=True).first()


def get_user_by_id(user_id: str) -> User | None:
    try:
        return User.objects.filter(pk=user_id).first()
    except (ValueError, TypeError):
        return None


def get_initials(name: str) -> str:
    return ''.join(word[0] for word in name.split()[:2]).upper()


# (key, label) for each update people choose in-app and email delivery for.
NOTIFICATION_UPDATES = (
    ('rsvp', 'RSVP confirmations'),
    ('reminders', 'Event reminders'),
    ('waitlist', 'Waitlist updates'),
    ('changes', 'Event changes'),
    ('new_events', 'New events from orgs you follow'),
)


def get_preferences(profile) -> dict:
    """Saved settings from `notification_prefs`, with defaults for anything not saved yet."""
    saved = profile.notification_prefs or {}
    notifications = {
        key: {'app': True, 'email': key != 'new_events', **saved.get('notifications', {}).get(key, {})}
        for key, _ in NOTIFICATION_UPDATES
    }
    return {
        'notifications': notifications,
        'feed': {'default_tab': 'for_you', 'free_only': False, **saved.get('feed', {})},
        'location': {
            'use': 'session',
            'start_with_walk': True,
            'show_heat_map': True,
            'default_map_view': 'map',
            **saved.get('location', {}),
        },
    }
