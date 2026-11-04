from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.login_user, name='login'),
    path('signup/', views.signup_user, name='signup'),
    path('logout/', views.logout_user, name='logout'),
    path('profile/', views.edit_profile, name='profile'),
    path('preferences/', views.edit_preferences, name='preferences'),
    path('preferences/following/<slug:slug>/', views.update_followed_organization, name='update_followed_organization'),
    path('verify-email/sent/', views.show_verification_sent, name='verification_sent'),
    path('verify-email/resend/', views.resend_verification_email, name='resend_verification_email'),
    path('verify-email/<str:token>/', views.verify_email, name='verify_email'),
]
