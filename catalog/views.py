from django.shortcuts import get_object_or_404, render

from .models import Game


def index(request):
    games = Game.objects.all()
    return render(request, 'catalog/index.html', {'games': games})


def game_detail(request, pk):
    game = get_object_or_404(Game, pk=pk)
    return render(request, 'catalog/game_detail.html', {'game': game})