from django.urls import path

from . import views

urlpatterns = [
    path('events/<uuid:event_id>/rsvp/', views.rsvp_to_event_or_cancel, name='rsvp'),
]
