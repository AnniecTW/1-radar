from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.views import get_account_shell_context
from apps.discovery.selectors import get_campus_timezone

from .models import Notification
from .presentation import describe_notification
from .selectors import list_notifications
from .services import mark_all_notifications_read, mark_notification_read


@login_required
@require_http_methods(['GET'])
def list_notifications_page(request: HttpRequest) -> HttpResponse:
    unread_only = request.GET.get('filter') == 'unread'
    rows = [describe_notification(item) for item in list_notifications(request.user, unread_only=unread_only)]
    with timezone.override(get_campus_timezone()):
        return render(request, 'notifications/list.html', {
            **get_account_shell_context(request.user),
            'rows': rows,
            'unread_only': unread_only,
        })


@login_required
@require_POST
def open_notification(request: HttpRequest, notification_id: int) -> HttpResponse:
    """Mark one read, then go to what it is about."""
    try:
        notification = mark_notification_read(user=request.user, notification_id=notification_id)
    except Notification.DoesNotExist:
        messages.error(request, 'That notification no longer exists.')
        return redirect('list_notifications')
    return redirect(describe_notification(notification)['url'])


@login_required
@require_POST
def read_all_notifications(request: HttpRequest) -> HttpResponse:
    mark_all_notifications_read(user=request.user)
    return redirect('list_notifications')
