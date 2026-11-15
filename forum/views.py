from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.db import transaction

from types import SimpleNamespace
from datetime import timedelta

from catalog.models import Game

from .forms import InviteForm, PostForm, TopicForm
from .models import GameInvite, Post, Topic

POSTS_PER_PAGE = 20
CHAT_PER_PAGE = 30
UPDATES_BATCH = 50
MAX_ACTIVE_INVITES = 3
INVITE_KEEP_AFTER_END = timedelta(hours=1)

DEFAULT_TOPIC_SORT = 'new'
TOPIC_SORTS = {
    'new': ('-last_activity', '-pk'),
    'old': ('created_at', 'pk'),
    'popular': ('-posts_count', '-last_activity', '-pk'),
}
TOPIC_SORT_LABELS = [
    ('popular', 'Популярные'),
    ('new', 'Недавно'),
    ('old', 'Давно'),
]


def topic_list(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)

    sort = request.GET.get('sort')
    if sort not in TOPIC_SORTS:
        sort = DEFAULT_TOPIC_SORT

    topics = (
        game.topics.select_related('author')
        .annotate(posts_count=Count('posts', filter=Q(posts__is_deleted=False)))
        .order_by(*TOPIC_SORTS[sort])
    )
    page = Paginator(topics, 20).get_page(request.GET.get('page'))
    return render(request, 'forum/topic_list.html', {
        'game': game,
        'page': page,
        'sort': sort,
        'sort_options': TOPIC_SORT_LABELS,
    })


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
        Topic.objects.select_related('game', 'author__profile'), pk=pk
    )

    if request.method == 'POST':
        if topic.is_deleted:
            raise PermissionDenied
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        form = PostForm(request.POST, request.FILES)
        reply_target = _reply_target(topic.posts.all(), request.POST.get('reply_to'))
        if form.is_valid():
            with transaction.atomic():
                post = form.save(commit=False)
                post.topic = topic
                post.author = request.user
                post.reply_to = reply_target
                post.save()
                form.save_images(post)
            Topic.objects.filter(pk=topic.pk).update(last_activity=timezone.now())
            return redirect('post_permalink', pk=post.pk)
    else:
        form = PostForm()
        reply_target = _reply_target(topic.posts.all(), request.GET.get('reply'))

    posts = topic.posts.select_related('author__profile', 'reply_to__author').prefetch_related('images')
    page = Paginator(posts, POSTS_PER_PAGE).get_page(request.GET.get('page'))
    return render(request, 'forum/topic_detail.html', {
        'topic': topic,
        'page': page,
        'form': form,
        'reply_target': reply_target,
        'last_id': max((post.pk for post in page), default=0),
        'live': not page.has_next(),
    })

def _to_int(raw, default=0):
    """Безопасно превращает строку из запроса в число."""
    raw = str(raw or '')
    return int(raw) if raw.isdecimal() and len(raw) < 10 else default


def _reply_target(posts, raw_id):
    """Сообщение, на которое отвечают: только из переданного набора."""
    reply_id = _to_int(raw_id)
    if reply_id:
        return (
            posts.select_related('author')
            .filter(pk=reply_id, is_deleted=False)
            .first()
        )
    return None

def post_permalink(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if post.topic_id:
        siblings = Post.objects.filter(topic_id=post.topic_id)
        per_page = POSTS_PER_PAGE
        url = reverse('topic_detail', args=[post.topic_id])
    else:
        siblings = Post.objects.filter(game_id=post.game_id)
        per_page = CHAT_PER_PAGE
        url = reverse('game_chat', args=[post.game_id])
    position = siblings.filter(pk__lt=post.pk).count()
    page_number = position // per_page + 1
    return redirect(f'{url}?page={page_number}#post-{post.pk}')

@login_required
def post_edit(request, pk):
    post = get_object_or_404(Post.objects.select_related('topic', 'game'), pk=pk)
    # Править текст может только автор, и только не удалённое сообщение
    if post.author_id != request.user.pk or post.is_deleted:
        raise PermissionDenied

    if request.method == 'POST':
        form = PostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            if form.has_real_changes():
                with transaction.atomic():
                    post = form.save(commit=False)
                    post.edited_at = timezone.now()
                    post.save(update_fields=['body', 'edited_at'])
                    form.save_images(post)
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
        post.images.all().delete()
        post.is_deleted = True
        post.body = ''
        post.save(update_fields=['is_deleted', 'body'])
        messages.success(request, 'Сообщение удалено.')
    return redirect('post_permalink', pk=post.pk)

def game_chat(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)
    chat_posts = game.chat_posts.all()

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        form = PostForm(request.POST, request.FILES)
        reply_target = _reply_target(chat_posts, request.POST.get('reply_to'))
        if form.is_valid():
            with transaction.atomic():
                post = form.save(commit=False)
                post.game = game
                post.author = request.user
                post.reply_to = reply_target
                post.save()
                form.save_images(post)
            return redirect('post_permalink', pk=post.pk)
    else:
        form = PostForm()
        reply_target = _reply_target(chat_posts, request.GET.get('reply'))

    posts = chat_posts.select_related('author__profile', 'reply_to__author').prefetch_related('images')
    paginator = Paginator(posts, CHAT_PER_PAGE)
    # Без номера страницы открываем последнюю: новые сообщения внизу
    page = paginator.get_page(request.GET.get('page') or paginator.num_pages)
    return render(request, 'forum/game_chat.html', {
        'game': game,
        'page': page,
        'form': form,
        'reply_target': reply_target,
        'last_id': max((post.pk for post in page), default=0),
        'live': not page.has_next(),
    })

@login_required
def topic_delete(request, pk):
    topic = get_object_or_404(Topic.objects.select_related('game'), pk=pk)
    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == 'POST':
        game_pk = topic.game_id
        title = topic.title
        topic.delete()
        messages.success(request, f'Тема «{title}» удалена вместе со всеми сообщениями.')
        return redirect('topic_list', game_pk=game_pk)

    return render(request, 'forum/topic_delete.html', {
        'topic': topic,
        'posts_count': topic.posts.count(),
    })

def _updates_response(request, posts):
    """JSON с HTML новых сообщений, id которых больше параметра after."""
    after = request.GET.get('after', '')
    if not after.isdecimal() or len(after) > 9:
        return JsonResponse({'error': 'bad request'}, status=400)
    page_number = _to_int(request.GET.get('page'), 1) or 1

    batch = list(
        posts.filter(pk__gt=int(after))
        .select_related('author__profile', 'reply_to__author')
        .prefetch_related('images')
        .order_by('pk')[:UPDATES_BATCH + 1]
    )
    has_more = len(batch) > UPDATES_BATCH
    batch = batch[:UPDATES_BATCH]
    if not batch:
        return JsonResponse({'count': 0})

    # Сквозной номер первого нового сообщения: так же считает пагинатор
    first_number = posts.filter(pk__lt=batch[0].pk).count() + 1
    html = render_to_string(
        'forum/_posts_fragment.html',
        {
            'posts': batch,
            'page': SimpleNamespace(number=page_number, start_index=first_number),
        },
        request=request,
    )
    return JsonResponse({
        'html': html,
        'count': len(batch),
        'last_id': batch[-1].pk,
        'has_more': has_more,
    })


@require_GET
@never_cache
def game_chat_updates(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)
    return _updates_response(request, game.chat_posts.all())


@require_GET
@never_cache
def topic_updates(request, pk):
    topic = get_object_or_404(Topic, pk=pk)
    return _updates_response(request, topic.posts.all())

def _active_invites(game):
    return game.invites.active().select_related('author__profile')


def _purge_old_invites():
    border = timezone.now() - INVITE_KEEP_AFTER_END
    GameInvite.objects.filter(Q(expires_at__lt=border) | Q(closed_at__lt=border)).delete()


def invite_list(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        form = InviteForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            has_steam = bool(getattr(getattr(request.user, 'profile', None), 'steam_id', ''))
            active_count = GameInvite.objects.active().filter(author=request.user).count()
            if active_count >= MAX_ACTIVE_INVITES:
                form.add_error(
                    None,
                    f'Одновременно можно держать не более {MAX_ACTIVE_INVITES} приглашений. '
                    'Завершите одно из прежних.',
                )
            elif not (data['link'] or data['join_code'] or has_steam):
                form.add_error(
                    None,
                    'Укажите ссылку, код лобби или адрес сервера. Если у игры нет ни ссылки, '
                    'ни кода, привяжите Steam в профиле: тогда в приглашении появится ссылка '
                    'на ваш профиль, и вас смогут добавить в друзья.',
                )
            else:
                _purge_old_invites()
                invite = form.save(commit=False)
                invite.game = game
                invite.author = request.user
                invite.expires_at = timezone.now() + timedelta(hours=data['hours'])
                invite.save()
                messages.success(request, 'Приглашение опубликовано.')
                return redirect('invite_list', game_pk=game.pk)
    else:
        form = InviteForm()

    invites = list(_active_invites(game))
    my_active = 0
    if request.user.is_authenticated:
        my_active = GameInvite.objects.active().filter(author=request.user).count()
    return render(request, 'forum/invite_list.html', {
        'game': game,
        'form': form,
        'invites': invites,
        'version': ','.join(str(invite.pk) for invite in invites),
        'my_active': my_active,
        'max_active': MAX_ACTIVE_INVITES,
    })


@login_required
@require_POST
def invite_close(request, game_pk, pk):
    invite = get_object_or_404(GameInvite, pk=pk, game_id=game_pk)
    if invite.author_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied
    if invite.is_active:
        invite.closed_at = timezone.now()
        invite.save(update_fields=['closed_at'])
        messages.success(request, 'Приглашение завершено.')
    return redirect('invite_list', game_pk=game_pk)


@require_GET
@never_cache
def invite_updates(request, game_pk):
    game = get_object_or_404(Game, pk=game_pk)
    invites = list(_active_invites(game))
    version = ','.join(str(invite.pk) for invite in invites)
    if request.GET.get('v') == version:
        return JsonResponse({'changed': False})
    html = render_to_string(
        'forum/_invite_list.html', {'invites': invites, 'game': game}, request=request
    )
    return JsonResponse({'changed': True, 'html': html, 'version': version})