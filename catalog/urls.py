from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='home'),
    path('games/<int:pk>/', views.game_detail, name='game_detail'),
]