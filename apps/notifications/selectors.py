from django.db.models import QuerySet

from .models import Notification

NOTIFICATION_PAGE_SIZE = 50


def count_unread_notifications(user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def list_notifications(user, *, unread_only: bool = False) -> QuerySet[Notification]:
    """Newest first, capped. Cancelled events stay linkable, so nothing is filtered by event state."""
    notifications = Notification.objects.filter(user=user).select_related('event', 'organization')
    if unread_only:
        notifications = notifications.filter(read_at__isnull=True)
    return notifications.order_by('-created_at', '-pk')[:NOTIFICATION_PAGE_SIZE]
