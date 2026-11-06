from django.urls import path

from . import views

urlpatterns = [
    path('events/<uuid:event_id>/analytics/', views.show_event_analytics, name='event_analytics'),
    path('events/<uuid:event_id>/attendees.csv', views.export_attendee_csv, name='export_attendee_csv'),
]
