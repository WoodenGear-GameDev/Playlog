from django.urls import path

from . import views

urlpatterns = [
    path('game/<int:game_pk>/', views.topic_list, name='topic_list'),
    path('game/<int:game_pk>/new/', views.topic_create, name='topic_create'),
    path('topic/<int:pk>/', views.topic_detail, name='topic_detail'),
    path('post/<int:pk>/', views.post_permalink, name='post_permalink'),
]