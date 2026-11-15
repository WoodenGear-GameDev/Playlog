from dataclasses import dataclass, field
import logging
from django.db import transaction
from django.utils import timezone

from .models import Achievement, Category, Game
from .steam_service import (
    SteamAPIError,
    SteamDataValidationError,
    fetch_app_details,
    fetch_game_review_summary,
    fetch_global_achievement_percentages,
    fetch_schema_achievements,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    ok: bool
    changed: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    error: str = ''

    def __bool__(self):
        return self.ok


def describe_result(result):
    """Текст сообщения для администратора."""
    if not result.ok:
        return result.error
    if result.changed:
        text = 'Обновлено: ' + ', '.join(result.changed) + '.'
    else:
        text = 'Данные уже актуальны.'
    if result.missing:
        text += ' Steam не прислал: ' + ', '.join(result.missing) + ' (оставлены прежние значения).'
    return text


def import_game_from_steam(steam_app_id: int):
    """Быстрый импорт игры из Steam Store API (без схемы достижений).

    Выполняет только получение метаданных и сводки отзывов из магазина Steam.
    Не блокирует добавление игры загрузкой десятков достижений.
    Выставляет schema_status = NOT_FETCHED.
    """
    from accounts.models import LibraryGame

    # 1. Запрашиваем метаданные игры из Steam Store API
    data = fetch_app_details(steam_app_id)

    title = (data.get('title') or '').strip()
    if not title:
        raise SteamDataValidationError(f'Steam Store API не вернул название для игры {steam_app_id}.')

    header_image = (data.get('header_image') or '').strip()
    if not header_image:
        raise SteamDataValidationError(f'Steam Store API не вернул обложку для игры «{title}».')

    # 2. Запрашиваем сводку отзывов Steam
    review_summary = fetch_game_review_summary(steam_app_id)

    # 3. Атомарное сохранение игры в каталог
    with transaction.atomic():
        game, created = Game.objects.get_or_create(steam_app_id=steam_app_id)
        game.title = title
        game.header_image = header_image
        game.description = (data.get('description') or '').strip()
        game.release_date = data.get('release_date')
        game.steam_review_desc = review_summary.get('desc', '')
        game.steam_review_percent = review_summary.get('percent') or 0
        game.steam_review_total = review_summary.get('total', 0)
        if created or game.schema_status != Game.SchemaStatus.READY:
            game.schema_status = Game.SchemaStatus.NOT_FETCHED
        game.save()

        # Категории / Жанры
        names = data.get('categories') or []
        if names:
            categories = [Category.objects.get_or_create(name=name)[0] for name in names]
            game.categories.set(categories)

        # Обновляем пустые обложки в библиотеках
        LibraryGame.objects.filter(steam_app_id=steam_app_id, header_image='').update(header_image=header_image)

    logger.info('Successfully imported game %s (AppID %s) from Steam Store', game.title, steam_app_id)
    return game


def sync_game_achievements_schema(game: Game) -> int:
    """Загружает или обновляет схему достижений игры и их глобальную редкость.

    Вызывается отдельно от добавления игры (по требованию со страницы игры).
    Выставляет schema_status = READY, NO_ACHIEVEMENTS или ERROR.
    Возвращает количество загруженных достижений.
    """
    game.schema_status = Game.SchemaStatus.FETCHING
    game.schema_last_attempt_at = timezone.now()
    game.save(update_fields=['schema_status', 'schema_last_attempt_at'])

    try:
        schema_achievements = fetch_schema_achievements(game.steam_app_id)
        global_percents = {}
        if schema_achievements:
            global_percents = fetch_global_achievement_percentages(game.steam_app_id)
    except SteamAPIError as e:
        logger.error('Failed to sync achievements schema for %s: %s', game.title, e)
        game.schema_status = Game.SchemaStatus.ERROR
        game.schema_error = str(e)
        game.schema_last_attempt_at = timezone.now()
        game.save(update_fields=['schema_status', 'schema_error', 'schema_last_attempt_at'])
        return 0

    with transaction.atomic():
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
            game.schema_status = Game.SchemaStatus.READY
            game.schema_error = ''
        else:
            game.achievements.all().delete()
            game.schema_status = Game.SchemaStatus.NO_ACHIEVEMENTS
            game.schema_error = ''

        game.schema_last_attempt_at = timezone.now()
        game.save(update_fields=['schema_status', 'schema_error', 'schema_last_attempt_at'])

    logger.info('Successfully synced %d schema achievements for %s', len(schema_achievements), game.title)
    return len(schema_achievements)


def sync_game(game, overwrite=False):
    """Полная синхронизация игры: метаданные, отзывы и схема достижений (для админки)."""
    import_game_from_steam(game.steam_app_id)
    ach_count = sync_game_achievements_schema(game)

    changed_items = ['метаданные']
    if ach_count:
        changed_items.append(f'{ach_count} достижений')
    if game.steam_review_total:
        changed_items.append('отзывы Steam')
    return SyncResult(True, changed=changed_items)


def resync_game_steam(game):
    """Обновляет отзывы и редкость достижений из Steam для существующей игры."""
    review_summary = fetch_game_review_summary(game.steam_app_id)
    global_percents = fetch_global_achievement_percentages(game.steam_app_id)

    with transaction.atomic():
        game.steam_review_desc = review_summary.get('desc', '')
        game.steam_review_percent = review_summary.get('percent') or 0
        game.steam_review_total = review_summary.get('total', 0)
        game.save(update_fields=[
            'steam_review_desc',
            'steam_review_percent',
            'steam_review_total',
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
