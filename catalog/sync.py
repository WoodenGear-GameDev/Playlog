import logging
from django.db import transaction

from .models import Achievement, Category
from .steam_service import (
    SteamAPIError,
    SteamDataValidationError,
    fetch_app_details,
    fetch_schema_achievements,
)

logger = logging.getLogger(__name__)


def sync_game(game, overwrite=False):
    """Синхронизирует игру со всеми метаданными и достижениями из Steam.

    Атомарная транзакция: если хоть один запрос завершился ошибкой или вернул
    неполные данные, выбрасывается SteamAPIError, транзакция откатывается и
    в базу данных НИЧЕГО не сохраняется.
    """
    # 1. Запрашиваем полные метаданные игры из Steam Store API
    data = fetch_app_details(game.steam_app_id)

    title = (data.get('title') or '').strip()
    if not title:
        raise SteamDataValidationError(f'Steam Store API не вернул название для игры {game.steam_app_id}.')

    header_image = (data.get('header_image') or '').strip()
    if not header_image:
        raise SteamDataValidationError(f'Steam Store API не вернул обложку для игры «{title}».')

    # 2. Запрашиваем схему всех достижений из Steam Web API
    schema_achievements = fetch_schema_achievements(game.steam_app_id)

    # 3. Атомарное сохранение в БД: только если всё получено успешно
    with transaction.atomic():
        game.title = title
        game.header_image = header_image
        game.description = (data.get('description') or '').strip()
        game.release_date = data.get('release_date')
        game.save()

        # Категории / Жанры
        names = data.get('categories') or []
        if names:
            categories = [Category.objects.get_or_create(name=name)[0] for name in names]
            game.categories.set(categories)

        # Достижения
        if schema_achievements:
            to_create = [
                Achievement(
                    game=game,
                    api_name=a['api_name'],
                    name=a['name'],
                    description=a['description'],
                    icon_url=a['icon_url'],
                    icon_gray_url=a['icon_gray_url'],
                )
                for a in schema_achievements
            ]
            Achievement.objects.bulk_create(
                to_create,
                update_conflicts=True,
                update_fields=['name', 'description', 'icon_url', 'icon_gray_url'],
                unique_fields=['game', 'api_name'],
            )
        else:
            game.achievements.all().delete()

    logger.info('Successfully synced game %s with %d achievements', game.title, len(schema_achievements))
    return True
