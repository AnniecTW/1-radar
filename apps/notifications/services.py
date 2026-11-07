from django.utils import timezone

from .models import Notification


def mark_notification_read(*, user, notification_id: int) -> Notification:
    """Only the owner can mark a notification; anyone else gets DoesNotExist."""
    notification = Notification.objects.select_related('event', 'organization').get(pk=notification_id, user=user)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=['read_at'])
    return notification


def mark_all_notifications_read(*, user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=timezone.now())

