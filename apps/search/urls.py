from django.urls import path

from . import views

# Staff analytics. They live in the search app, which the recommendations tab borrows for its view and URL.
urlpatterns = [
    path('analytics/search/', views.show_search_dashboard, name='search_dashboard'),
    path('analytics/recommendations/', views.show_recommendation_dashboard, name='recommendation_dashboard'),
]
