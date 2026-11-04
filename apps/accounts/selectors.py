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
