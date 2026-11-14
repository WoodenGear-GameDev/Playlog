from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator

from .forms import RatingForm
from .models import Category, Game, Rating

RESULTS_PER_PAGE = 24


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
    return render(request, 'catalog/game_detail.html', {
        'game': game,
        'stats': stats,
        'user_rating': user_rating,
        'rating_form': rating_form,
    })


@login_required
@require_POST
def rate_game(request, pk):
    game = get_object_or_404(Game, pk=pk)
    form = RatingForm(request.POST)
    if form.is_valid():
        Rating.objects.update_or_create(
            user=request.user,
            game=game,
            defaults={'value': form.cleaned_data['value']},
        )
        messages.success(request, 'Оценка сохранена.')
    else:
        messages.error(request, 'Выберите оценку от 1 до 10.')
    return redirect('game_detail', pk=game.pk)


@login_required
@require_POST
def delete_rating(request, pk):
    game = get_object_or_404(Game, pk=pk)
    Rating.objects.filter(user=request.user, game=game).delete()
    messages.success(request, 'Оценка удалена.')
    return redirect('game_detail', pk=game.pk)