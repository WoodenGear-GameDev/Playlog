from urllib.parse import urlencode

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
from .models import Category, Game, Rating, ReviewVote

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

    return render(request, 'catalog/game_detail.html', {
        'game': game,
        'stats': stats,
        'user_rating': user_rating,
        'rating_form': rating_form,
        'reviews': reviews,
        'reviews_page': reviews_page,
        'sort': sort,
        'sort_options': REVIEW_SORT_LABELS,
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