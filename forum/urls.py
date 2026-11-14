from django.urls import path

from . import views

urlpatterns = [
    path('game/<int:game_pk>/', views.topic_list, name='topic_list'),
    path('game/<int:game_pk>/new/', views.topic_create, name='topic_create'),
    path('topic/<int:pk>/', views.topic_detail, name='topic_detail'),
    path('post/<int:pk>/', views.post_permalink, name='post_permalink'),
    path('post/<int:pk>/edit/', views.post_edit, name='post_edit'),
    path('post/<int:pk>/delete/', views.post_delete, name='post_delete'),
    path('game/<int:game_pk>/chat/', views.game_chat, name='game_chat'),
    path('topic/<int:pk>/delete/', views.topic_delete, name='topic_delete'),
    path('game/<int:game_pk>/chat/updates/', views.game_chat_updates, name='game_chat_updates'),
    path('topic/<int:pk>/updates/', views.topic_updates, name='topic_updates'),
]