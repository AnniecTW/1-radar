from django.urls import path

from . import views

urlpatterns = [
    path('events/<uuid:event_id>/save/', views.save_event, name='save_event'),
    path('events/<uuid:event_id>/like/', views.like_event, name='like_event'),
    path('events/<uuid:event_id>/tickets/', views.go_to_tickets, name='event_tickets'),
    path('organizations/<slug:slug>/follow/', views.follow_organization_view, name='follow_organization'),
]
