"""
URL configuration for radar project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.discovery.views import show_landing_page
from apps.discovery.views import (
    dismiss_recommendation_view, events_in_map_bounds, set_recommendation_location, share_location,
    show_explore_map, turn_off_recommendation_location,
)
from apps.events.views import show_event_detail

urlpatterns = [
    path('', show_landing_page, name='dashboard'),
    path('explore/', show_explore_map, name='explore_map'),
    path('api/map-events/', events_in_map_bounds, name='map_events'),
    path('api/location/', share_location, name='share_location'),
    path('api/recommendation-location/', set_recommendation_location, name='set_recommendation_location'),
    path('api/recommendation-location/off/', turn_off_recommendation_location,
         name='turn_off_recommendation_location'),
    path('api/recommendations/<uuid:event_id>/dismiss/', dismiss_recommendation_view,
         name='dismiss_recommendation'),
    path('events/<slug:slug>/', show_event_detail, name='event_detail'),
    path('accounts/', include('apps.accounts.urls')),
    path('onboarding/', include('apps.interests.urls')),
    path('', include('apps.rsvps.urls')),
    path('', include('apps.flyers.urls')),
    path('', include('apps.events.urls')),
    path('', include('apps.analytics.urls')),
    path('', include('apps.engagement.urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('organizations/', include('apps.organizations.urls')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
