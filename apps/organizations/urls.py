from django.urls import path

from . import views

urlpatterns = [
    path('', views.list_my_organizations, name='list_my_organizations'),
    path('new/', views.create_organization_profile, name='create_organization'),
    path('<slug:slug>/', views.show_organization_profile, name='show_organization_profile'),
    path('<slug:slug>/verify/', views.request_verification, name='request_organization_verification'),
    path('<slug:slug>/members/', views.manage_members, name='manage_organization_members'),
    path('<slug:slug>/members/add/', views.add_member, name='add_organization_member'),
    path('<slug:slug>/members/<int:membership_id>/role/', views.set_member_role, name='set_organization_member_role'),
    path('<slug:slug>/members/<int:membership_id>/remove/', views.remove_member, name='remove_organization_member'),
    path('<slug:slug>/members/<int:membership_id>/make-owner/', views.make_owner, name='transfer_organization_ownership'),
    path('<slug:slug>/leave/', views.leave, name='leave_organization'),
    path('<slug:slug>/delete/', views.delete, name='delete_organization'),
    path('<slug:slug>/edit/', views.edit_organization_profile, name='edit_organization_profile'),
]
