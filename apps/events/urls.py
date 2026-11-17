from django.urls import path

from . import views

urlpatterns = [
    path('my-events/', views.show_my_events, name='my_events'),
    path('my-events/new/', views.create_event_page, name='create_event'),
    path('events/<uuid:event_id>/edit/', views.edit_event_page, name='edit_event'),
    path('events/<uuid:event_id>/cancel/', views.cancel_hosted_event, name='cancel_hosted_event'),
    path('events/<uuid:event_id>/publish/', views.publish_draft_event, name='publish_draft_event'),
]
