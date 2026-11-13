from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import RatingForm
from .models import Category, Game, Rating

def index(request):
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