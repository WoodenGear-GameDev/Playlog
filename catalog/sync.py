import logging
from django.db import transaction
from django.utils import timezone

from .models import Achievement, Category
from .steam_service import (
    SteamAPIError,
    SteamDataValidationError,
    fetch_app_details,
    fetch_game_review_summary,
    fetch_global_achievement_percentages,
    fetch_schema_achievements,
)

logger = logging.getLogger(__name__)


def sync_game(game, overwrite=False):
    """Синхронизирует игру со всеми метаданными, отзывами и достижениями из Steam.

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

    # 2. Запрашиваем сводку отзывов Steam
    review_summary = fetch_game_review_summary(game.steam_app_id)

    # 3. Запрашиваем схему всех достижений и их глобальную редкость
    schema_achievements = fetch_schema_achievements(game.steam_app_id)
    global_percents = {}
    if schema_achievements:
        global_percents = fetch_global_achievement_percentages(game.steam_app_id)

    # 4. Атомарное сохранение в БД: только если всё получено успешно
    with transaction.atomic():
        game.title = title
        game.header_image = header_image
        game.description = (data.get('description') or '').strip()
        game.release_date = data.get('release_date')
        game.steam_review_desc = review_summary.get('desc', '')
        game.steam_review_percent = review_summary.get('percent')
        game.steam_review_total = review_summary.get('total', 0)
        game.steam_synced_at = timezone.now()
        game.save()

        # Категории / Жанры
        names = data.get('categories') or []
        if names:
            categories = [Category.objects.get_or_create(name=name)[0] for name in names]
            game.categories.set(categories)

        # Достижения с процентом редкости
        if schema_achievements:
            to_create = [
                Achievement(
                    game=game,
                    api_name=a['api_name'],
                    name=a['name'],
                    description=a['description'],
                    icon_url=a['icon_url'],
                    icon_gray_url=a['icon_gray_url'],
                    global_percent=round(global_percents.get(a['api_name'], 0.0), 1),
                )
                for a in schema_achievements
            ]
            Achievement.objects.bulk_create(
                to_create,
                update_conflicts=True,
                update_fields=['name', 'description', 'icon_url', 'icon_gray_url', 'global_percent'],
                unique_fields=['game', 'api_name'],
            )
        else:
            game.achievements.all().delete()

    logger.info('Successfully synced game %s with %d achievements and reviews', game.title, len(schema_achievements))
    return True


def resync_game_steam(game):
    """Обновляет отзывы и редкость достижений из Steam для существующей игры."""
    review_summary = fetch_game_review_summary(game.steam_app_id)
    global_percents = fetch_global_achievement_percentages(game.steam_app_id)

    with transaction.atomic():
        game.steam_review_desc = review_summary.get('desc', '')
        game.steam_review_percent = review_summary.get('percent')
        game.steam_review_total = review_summary.get('total', 0)
        game.steam_synced_at = timezone.now()
        game.save(update_fields=[
            'steam_review_desc',
            'steam_review_percent',
            'steam_review_total',
            'steam_synced_at',
        ])

        if global_percents:
            achievements_to_update = []
            for ach in game.achievements.all():
                if ach.api_name in global_percents:
                    val = global_percents[ach.api_name]
                    if ach.global_percent != val:
                        ach.global_percent = val
                        achievements_to_update.append(ach)
            if achievements_to_update:
                Achievement.objects.bulk_update(achievements_to_update, ['global_percent'])

    logger.info('Successfully resynced Steam data for game %s', game.title)
    return True
