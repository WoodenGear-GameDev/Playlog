from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalog.models import Game

from .forms import PostForm, TopicForm
from .models import Post, Topic

POSTS_PER_PAGE = 20


def topic_list(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)
    topics = (
        game.topics.select_related('author')
        .annotate(posts_count=Count('posts', filter=Q(posts__is_deleted=False)))
        .order_by('-last_activity', '-pk')
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
        reply_target = _reply_target(topic.posts.all(), request.POST.get('reply_to'))
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
        reply_target = _reply_target(topic.posts.all(), request.GET.get('reply'))

    posts = topic.posts.select_related('author', 'reply_to__author')
    page = Paginator(posts, POSTS_PER_PAGE).get_page(request.GET.get('page'))
    return render(request, 'forum/topic_detail.html', {
        'topic': topic,
        'page': page,
        'form': form,
        'reply_target': reply_target,
    })

def _reply_target(posts, raw_id):
    """Сообщение, на которое отвечают: только из переданного набора."""
    if raw_id and str(raw_id).isdigit():
        return (
            posts.select_related('author')
            .filter(pk=raw_id, is_deleted=False)
            .first()
        )
    return None

def post_permalink(request, pk):
    post = get_object_or_404(Post, pk=pk)
    position = Post.objects.filter(topic_id=post.topic_id, pk__lt=post.pk).count()
    page_number = position // POSTS_PER_PAGE + 1
    url = reverse('topic_detail', args=[post.topic_id])
    return redirect(f'{url}?page={page_number}#post-{post.pk}')

@login_required
def post_edit(request, pk):
    post = get_object_or_404(Post.objects.select_related('topic', 'game'), pk=pk)
    # Править текст может только автор, и только не удалённое сообщение
    if post.author_id != request.user.pk or post.is_deleted:
        raise PermissionDenied

    if request.method == 'POST':
        form = PostForm(request.POST, instance=post)
        if form.is_valid():
            if form.has_changed():
                post = form.save(commit=False)
                post.edited_at = timezone.now()
                post.save(update_fields=['body', 'edited_at'])
                messages.success(request, 'Сообщение изменено.')
            return redirect('post_permalink', pk=post.pk)
    else:
        form = PostForm(instance=post)
    return render(request, 'forum/post_edit.html', {'form': form, 'post': post})


@login_required
@require_POST
def post_delete(request, pk):
    post = get_object_or_404(Post, pk=pk)
    # Удалить может автор или сотрудник (модератор)
    if post.author_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied
    if not post.is_deleted:
        post.is_deleted = True
        post.body = ''
        post.save(update_fields=['is_deleted', 'body'])
        messages.success(request, 'Сообщение удалено.')
    return redirect('post_permalink', pk=post.pk)