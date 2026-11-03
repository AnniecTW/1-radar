from django.urls import path

from . import views

urlpatterns = [
    path('interests/', views.pick_interests, name='onboarding_interests'),
    path('organizations/', views.suggest_organizations, name='onboarding_organizations'),
    path('skip/', views.skip_onboarding, name='onboarding_skip'),
]
