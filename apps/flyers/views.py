from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .services import FlyerUploadError, daily_limit, process_flyer, uploads_left_today


@login_required
@require_http_methods(['GET', 'POST'])
def upload_flyer_page(request):
    """Snap-a-Flyer step 1: upload a flyer photo. Step 2 is the Create Event form, pre-filled."""
    from apps.accounts.views import get_account_shell_context

    user = request.user
    context = {**get_account_shell_context(user), 'active_nav': 'create_event'}
    if not user.is_campus_verified:
        context['needs_campus'] = True
        return render(request, 'flyers/upload.html', context)

    error = None
    if request.method == 'POST':
        upload = request.FILES.get('flyer')
        if not upload:
            error = 'Choose a photo of your flyer first.'
        else:
            try:
                flyer = process_flyer(user=user, upload=upload)
            except FlyerUploadError as exc:
                error = str(exc)
            except PermissionDenied:
                error = 'A verified campus member is required to host events.'
            else:
                if flyer.status != flyer.Status.SUCCEEDED:
                    messages.warning(
                        request,
                        "We couldn't read this flyer, so fill in the form yourself. "
                        'Your flyer is already attached as the cover image.',
                    )
                return redirect(f"{reverse('create_event')}?flyer={flyer.pk}")

    context.update({'error': error, 'uploads_left': uploads_left_today(user), 'daily_limit': daily_limit()})
    return render(request, 'flyers/upload.html', context, status=400 if error else 200)
