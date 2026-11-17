from django.urls import path

from . import views

urlpatterns = [
    path('', views.list_notifications_page, name='list_notifications'),
    path('read-all/', views.read_all_notifications, name='read_all_notifications'),
    path('<int:notification_id>/open/', views.open_notification, name='open_notification'),
]
