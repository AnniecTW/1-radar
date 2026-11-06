from django.urls import path

from . import views

urlpatterns = [
    path('', views.list_my_organizations, name='list_my_organizations'),
    path('new/', views.create_organization_profile, name='create_organization'),
    path('<slug:slug>/', views.show_organization_profile, name='show_organization_profile'),
    path('<slug:slug>/verify/', views.request_verification, name='request_organization_verification'),
    path('<slug:slug>/edit/', views.edit_organization_profile, name='edit_organization_profile'),
]
