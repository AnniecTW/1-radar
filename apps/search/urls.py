from django.urls import path

from . import views

urlpatterns = [
    path('analytics/search/', views.show_search_dashboard, name='search_dashboard'),
]
