from .models import Category
from .steam_service import fetch_app_details


def sync_game(game, overwrite=False):
    """Заполняет поля игры данными из Steam. Возвращает True при успехе."""
    try:
        data = fetch_app_details(game.steam_app_id)
    except Exception:
        return False
    if not data:
        return False

    for field in ('title', 'description', 'release_date', 'header_image'):
        value = data.get(field)
        if value and (overwrite or not getattr(game, field)):
            setattr(game, field, value)
    game.save()

    names = data.get('categories') or []
    if names and (overwrite or not game.categories.exists()):
        game.categories.set(
            [Category.objects.get_or_create(name=name)[0] for name in names]
        )
    return True
