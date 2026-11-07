from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.login_user, name='login'),
    path('signup/', views.signup_user, name='signup'),
    path('password-reset/', views.request_password_reset, name='request_password_reset'),
    path('password-reset/<str:uidb64>/<str:token>/', views.confirm_password_reset, name='confirm_password_reset'),
    path('logout/', views.logout_user, name='logout'),
    path('profile/', views.show_profile, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/following/<slug:slug>/', views.update_followed_organization, name='update_followed_organization'),
    path('profile/saved/<uuid:event_id>/remove/', views.remove_from_saved, name='remove_from_saved'),
    path('preferences/', views.edit_preferences, name='preferences'),
    path('preferences/account/', views.edit_account_preferences, name='account_preferences'),
    path('preferences/password/', views.change_password, name='change_password'),
    path('verify-email/sent/', views.show_verification_sent, name='verification_sent'),
    path('verify-email/resend/', views.resend_verification_email, name='resend_verification_email'),
    path('verify-email/<str:token>/', views.verify_email, name='verify_email'),
]
