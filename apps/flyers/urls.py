from django.urls import path

from . import views

urlpatterns = [
    path('my-events/new/flyer/', views.upload_flyer_page, name='upload_flyer'),
]
