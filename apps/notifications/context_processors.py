from .selectors import count_unread_notifications


def unread_notifications(request):
    """The bell badge on every signed-in page."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'unread_notification_count': count_unread_notifications(user)}
