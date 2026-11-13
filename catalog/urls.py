from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='home'),
    path('games/<int:pk>/', views.game_detail, name='game_detail'),
    path('games/<int:pk>/rate/', views.rate_game, name='rate_game'),
    path('games/<int:pk>/rate/delete/', views.delete_rating, name='delete_rating'),
]