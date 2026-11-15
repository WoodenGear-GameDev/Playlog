import logging
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Avg, Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import RatingForm
from .models import Achievement, Category, Game, Rating, ReviewVote

RESULTS_PER_PAGE = 24

REVIEWS_PER_PAGE = 10
DEFAULT_REVIEW_SORT = 'helpful'
REVIEW_SORTS = {
    'helpful': ('-score', '-created_at', '-pk'),
    'new': ('-created_at', '-pk'),
    'old': ('created_at', 'pk'),
    'high': ('-value', '-created_at', '-pk'),
    'low': ('value', '-created_at', '-pk'),
}
REVIEW_SORT_LABELS = [
    ('helpful', 'Полезные'),
    ('new', 'Недавно'),
    ('old', 'Давно'),
    ('high', 'Оценка: по убыванию'),
    ('low', 'Оценка: по возрастанию'),
]


def _search_games(query):
    """Возвращает id найденных игр, отсортированные по названию.

    Поиск идёт в Python, а не через SQL: встроенный LIKE в SQLite не
    различает регистр для кириллицы («мир» не нашёл бы «Мир»).
    """
    words = query.casefold().split()
    found = []
    for pk, title, app_id in Game.objects.values_list('pk', 'title', 'steam_app_id'):
        name = title.casefold()
        if all(word in name for word in words) or query == str(app_id):
            found.append((name, pk))
    found.sort()
    return [pk for _, pk in found]


from .steam_service import (
    SteamAPIError,
    fetch_app_details,
    fetch_player_unlocked_achievements,
    fetch_schema_achievements,
    search_steam_games,
)
from .sync import resync_game_steam, sync_game


def index(request):
    q = request.GET.get('q', '').strip()[:100]
    if q:
        paginator = Paginator(_search_games(q), RESULTS_PER_PAGE)
        page = paginator.get_page(request.GET.get('page'))
        games = Game.objects.in_bulk(list(page.object_list))
        results = [games[pk] for pk in page.object_list if pk in games]

        return render(request, 'catalog/index.html', {
            'q': q,
            'page': page,
            'results': results,
        })

    categories = Category.objects.prefetch_related('games')
    uncategorized = Game.objects.filter(categories__isnull=True)
    return render(request, 'catalog/index.html', {
        'categories': categories,
        'uncategorized': uncategorized,
    })


def steam_search_results(request):
    """Асинхронно ищет игры в Steam по запросу и отдаёт карточки для вставки."""
    q = request.GET.get('q', '').strip()[:100]
    if not q:
        return render(request, 'catalog/partials/steam_search_results.html', {'steam_results': []})

    from django.core.cache import cache

    cache_key = f'steam_search_{q.casefold()}'
    steam_items = cache.get(cache_key)
    if steam_items is None:
        steam_items = search_steam_games(q)
        cache.set(cache_key, steam_items, 3600)  # кэш поиска на 1 час

    existing_map = dict(
        Game.objects.filter(
            steam_app_id__in=[it['steam_app_id'] for it in steam_items]
        ).values_list('steam_app_id', 'pk')
    )
    steam_results = []
    for it in steam_items:
        appid = it['steam_app_id']
        existing_pk = existing_map.get(appid)
        steam_results.append({
            'steam_app_id': appid,
            'title': it['title'],
            'header_image': it['header_image'],
            'in_catalog': bool(existing_pk),
            'game_pk': existing_pk,
        })

    return render(request, 'catalog/partials/steam_search_results.html', {
        'steam_results': steam_results,
    })
    return render(request, 'catalog/index.html', {
        'categories': categories,
        'uncategorized': uncategorized,
    })


def steam_game_import(request, steam_app_id):
    """Импортирует игру из Steam в каталог с подтверждением."""
    game = Game.objects.filter(steam_app_id=steam_app_id).first()
    if game:
        return redirect('game_detail', pk=game.pk)

    if request.method == 'POST':
        try:
            game = Game(steam_app_id=steam_app_id)
            sync_game(game, overwrite=True)
            messages.success(
                request,
                f'Игра «{game.title}» успешно добавлена в каталог! Загружено достижений: {game.achievements.count()}.',
            )
            return redirect('game_detail', pk=game.pk)
        except SteamAPIError as e:
            logger.error('Failed to import Steam game %s: %s', steam_app_id, e)
            messages.error(request, f'Не удалось добавить игру из Steam: {e}')
            return redirect('home')

    return render(request, 'catalog/game_add_confirm.html', {
        'steam_app_id': steam_app_id,
        'title': request.GET.get('title', ''),
        'header_image': request.GET.get('img', ''),
    })


def game_detail(request, pk):
    game = get_object_or_404(Game, pk=pk)
    stats = game.ratings.aggregate(average=Avg('value'), count=Count('id'))
    user_rating = None
    rating_form = None
    if request.user.is_authenticated:
        user_rating = game.ratings.filter(user=request.user).first()
        rating_form = RatingForm(instance=user_rating)

    sort = request.GET.get('sort')
    if sort not in REVIEW_SORTS:
        sort = DEFAULT_REVIEW_SORT

    reviews_qs = (
        game.ratings.exclude(text='')
        .select_related('user')
        .annotate(
            helpful_count=Count('votes', filter=Q(votes__is_helpful=True)),
            unhelpful_count=Count('votes', filter=Q(votes__is_helpful=False)),
        )
        .annotate(score=F('helpful_count') - F('unhelpful_count'))
        .order_by(*REVIEW_SORTS[sort])
    )
    reviews_page = Paginator(reviews_qs, REVIEWS_PER_PAGE).get_page(
        request.GET.get('page')
    )
    reviews = list(reviews_page.object_list)

    my_votes = {}
    if request.user.is_authenticated and reviews:
        my_votes = dict(
            ReviewVote.objects.filter(
                user=request.user, rating_id__in=[r.pk for r in reviews]
            ).values_list('rating_id', 'is_helpful')
        )
    for review in reviews:
        vote = my_votes.get(review.pk)
        review.my_vote = None if vote is None else ('up' if vote else 'down')
        review.is_mine = (
            request.user.is_authenticated and review.user_id == request.user.pk
        )

    achievements = list(game.achievements.all())
    # Если игра привязана к Steam, но ачивки в БД отсутствуют — подтягиваем схему
    if not achievements and game.steam_app_id:
        schema = fetch_schema_achievements(game.steam_app_id)
        if schema:
            to_create = [
                Achievement(
                    game=game,
                    api_name=a['api_name'],
                    name=a['name'],
                    description=a['description'],
                    icon_url=a['icon_url'],
                    icon_gray_url=a['icon_gray_url'],
                )
                for a in schema
            ]
            Achievement.objects.bulk_create(to_create, ignore_conflicts=True)
            achievements = list(game.achievements.all())

    user_unlocked_count = 0
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        profile = request.user.profile
        unlocked_pks = set(
            profile.unlocked_achievements.filter(game=game).values_list('pk', flat=True)
        )
        # Если игра есть в библиотеке пользователя с выбитыми ачивками, но они ещё не связаны в БД — связываем
        if not unlocked_pks and profile.steam_id and achievements:
            lib_entry = profile.library.filter(steam_app_id=game.steam_app_id).first()
            if lib_entry and lib_entry.achievements_unlocked > 0:
                try:
                    unlocked_set, _, _ = fetch_player_unlocked_achievements(
                        profile.steam_id, game.steam_app_id
                    )
                    if unlocked_set:
                        matched = list(game.achievements.filter(api_name__in=unlocked_set))
                        profile.unlocked_achievements.add(*matched)
                        unlocked_pks = {a.pk for a in matched}
                except SteamAPIError as e:
                    logger.error('Failed to link achievements for %s on %s: %s', profile.user.username, game.title, e)

        user_unlocked_count = len(unlocked_pks)
        for ach in achievements:
            ach.is_unlocked = ach.pk in unlocked_pks
        achievements.sort(
            key=lambda a: (not getattr(a, 'is_unlocked', False), -getattr(a, 'global_percent', 0.0), a.pk)
        )

    return render(request, 'catalog/game_detail.html', {
        'game': game,
        'stats': stats,
        'user_rating': user_rating,
        'rating_form': rating_form,
        'reviews': reviews,
        'reviews_page': reviews_page,
        'sort': sort,
        'sort_options': REVIEW_SORT_LABELS,
        'achievements': achievements,
        'user_unlocked_count': user_unlocked_count,
    })


@login_required
@require_POST
def rate_game(request, pk):
    game = get_object_or_404(Game, pk=pk)
    form = RatingForm(request.POST)
    if form.is_valid():
        value = form.cleaned_data['value']
        text = form.cleaned_data['text']
        existing = Rating.objects.filter(user=request.user, game=game).first()
        if existing and existing.text != text:
            # Другой текст это уже другой отзыв: старые голоса к нему не относятся
            existing.votes.all().delete()
        Rating.objects.update_or_create(
            user=request.user,
            game=game,
            defaults={'value': value, 'text': text},
        )
        messages.success(
            request, 'Оценка и отзыв сохранены.' if text else 'Оценка сохранена.'
        )
    else:
        errors = [error for errs in form.errors.values() for error in errs]
        messages.error(request, ' '.join(errors) or 'Не удалось сохранить оценку.')
    return redirect('game_detail', pk=game.pk)


@login_required
@require_POST
def delete_rating(request, pk):
    game = get_object_or_404(Game, pk=pk)
    Rating.objects.filter(user=request.user, game=game).delete()
    messages.success(request, 'Оценка удалена.')
    return redirect('game_detail', pk=game.pk)


def _reviews_url(game_pk, sort, page):
    """Адрес списка отзывов: сортировку и страницу берём из формы, но проверяем."""
    params = {}
    if sort in REVIEW_SORTS:
        params['sort'] = sort
    page = str(page or '')
    if page.isdecimal() and len(page) < 6:
        params['page'] = page
    url = reverse('game_detail', args=[game_pk])
    if params:
        url += '?' + urlencode(params)
    return url + '#reviews'


@login_required
@require_POST
def vote_review(request, game_pk, pk):
    rating = get_object_or_404(Rating.objects.exclude(text=''), pk=pk, game_id=game_pk)
    choice = request.POST.get('vote')

    if rating.user_id == request.user.pk:
        messages.error(request, 'Свой отзыв оценивать нельзя.')
    elif choice in ('up', 'down'):
        is_helpful = choice == 'up'
        vote = ReviewVote.objects.filter(rating=rating, user=request.user).first()
        if vote and vote.is_helpful == is_helpful:
            vote.delete()  # повторный клик снимает голос
        elif vote:
            vote.is_helpful = is_helpful
            vote.save(update_fields=['is_helpful'])
        else:
            try:
                ReviewVote.objects.create(
                    rating=rating, user=request.user, is_helpful=is_helpful
                )
            except IntegrityError:
                pass  # двойной клик: голос уже записан

    return redirect(
        _reviews_url(game_pk, request.POST.get('sort'), request.POST.get('page'))
    )

@login_required
@require_POST
def delete_review(request, game_pk, pk):
    rating = get_object_or_404(Rating, pk=pk, game_id=game_pk)
    if rating.user_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied

    # Двойной клик: отзыв уже удалён, повторять нечего
    if rating.text:
        rating.votes.all().delete()
        rating.text = ''
        rating.save(update_fields=['text', 'updated_at'])
        messages.success(request, 'Отзыв удалён. Оценка сохранена.')

    return redirect(
        _reviews_url(game_pk, request.POST.get('sort'), request.POST.get('page'))
    )


@login_required
@require_POST
def game_steam_resync(request, pk):
    """Актуализирует отзывы и редкость достижений из Steam по запросу пользователя."""
    game = get_object_or_404(Game, pk=pk)
    if not game.steam_app_id:
        messages.error(request, 'Эта игра не привязана к Steam.')
        return redirect('game_detail', pk=game.pk)

    try:
        resync_game_steam(game)
        messages.success(request, f'Данные и отзывы Steam для «{game.title}» успешно обновлены!')
    except SteamAPIError as e:
        logger.error('Failed to resync Steam data for %s: %s', game.steam_app_id, e)
        messages.error(request, f'Не удалось обновить данные из Steam: {e}')
    except Exception as e:
        logger.exception('Unexpected error during Steam resync for %s', game.steam_app_id)
        messages.error(request, f'Произошла непредвиденная ошибка: {e}')

    return redirect('game_detail', pk=game.pk)

