from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from catalog.models import Game

from .forms import TopicForm
from .models import Topic


def topic_list(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)
    topics = game.topics.select_related('author').annotate(
        posts_count=Count('posts')
    )
    page = Paginator(topics, 20).get_page(request.GET.get('page'))
    return render(request, 'forum/topic_list.html', {'game': game, 'page': page})


@login_required
def topic_create(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)
    if request.method == 'POST':
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save(commit=False)
            topic.game = game
            topic.author = request.user
            topic.save()
            messages.success(request, 'Тема создана.')
            return redirect('topic_detail', pk=topic.pk)
    else:
        form = TopicForm()
    return render(request, 'forum/topic_create.html', {'game': game, 'form': form})


def topic_detail(request, pk):
    topic = get_object_or_404(
        Topic.objects.select_related('game', 'author'), pk=pk
    )
    posts = topic.posts.select_related('author', 'reply_to__author')
    return render(request, 'forum/topic_detail.html', {
        'topic': topic,
        'posts': posts,
    })