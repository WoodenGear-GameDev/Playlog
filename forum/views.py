from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from catalog.models import Game

from .forms import PostForm, TopicForm
from .models import Post, Topic

POSTS_PER_PAGE = 20


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

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        form = PostForm(request.POST)
        reply_target = _reply_target(topic, request.POST.get('reply_to'))
        if form.is_valid():
            post = form.save(commit=False)
            post.topic = topic
            post.author = request.user
            post.reply_to = reply_target
            post.save()
            Topic.objects.filter(pk=topic.pk).update(last_activity=timezone.now())
            return redirect('post_permalink', pk=post.pk)
    else:
        form = PostForm()
        reply_target = _reply_target(topic, request.GET.get('reply'))

    posts = topic.posts.select_related('author', 'reply_to__author')
    page = Paginator(posts, POSTS_PER_PAGE).get_page(request.GET.get('page'))
    return render(request, 'forum/topic_detail.html', {
        'topic': topic,
        'page': page,
        'form': form,
        'reply_target': reply_target,
    })

def _reply_target(topic, raw_id):
    """Сообщение, на которое отвечают. Ищем только внутри этой же темы."""
    if raw_id and str(raw_id).isdigit():
        return topic.posts.select_related('author').filter(pk=raw_id).first()
    return None

def post_permalink(request, pk):
    post = get_object_or_404(Post, pk=pk)
    position = Post.objects.filter(topic_id=post.topic_id, pk__lt=post.pk).count()
    page_number = position // POSTS_PER_PAGE + 1
    url = reverse('topic_detail', args=[post.topic_id])
    return redirect(f'{url}?page={page_number}#post-{post.pk}')