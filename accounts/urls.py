from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path(
        'login/',
        auth_views.LoginView.as_view(template_name='accounts/login.html'),
        name='login',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('activate/<uidb64>/<token>/', views.activate, name='activate'),
    path('register/done/', views.register_done, name='register_done'),
    path('resend/', views.resend_confirmation, name='resend_confirmation'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('steam/link/', views.steam_link_start, name='steam_link'),
    path('steam/callback/', views.steam_link_callback, name='steam_callback'),
    path('steam/unlink/', views.steam_unlink, name='steam_unlink'),
    path('library/<int:pk>/open/', views.library_open, name='library_open'),
]