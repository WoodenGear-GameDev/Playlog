import logging
import requests
from django.conf import settings

from catalog.models import Game
from catalog.steam_service import fetch_app_details

logger = logging.getLogger(__name__)

STEAM_OWNED_GAMES_URL = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/'


def fetch_user_library(steam_id: str):
    """Запрашивает список купленных/сыгранных игр пользователя из Steam Web API.

    Возвращает список словарей:
        [{'steam_app_id': int, 'name': str, 'playtime_minutes': int}, ...]
    или None при ошибке/скрытом профиле.
    """
    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key or not steam_id:
        return None

    params = {
        'key': api_key,
        'steamid': steam_id,
        'include_appinfo': 1,
        'include_played_free_games': 1,
        'format': 'json',
    }

    try:
        response = requests.get(STEAM_OWNED_GAMES_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning('Failed to fetch Steam library for %s: %s', steam_id, e)
        return None

    games_data = data.get('response', {}).get('games')
    if games_data is None:
        return None

    results = []
    for item in games_data:
        appid = item.get('appid')
        if not appid:
            continue
        results.append({
            'steam_app_id': appid,
            'name': item.get('name', ''),
            'playtime_minutes': item.get('playtime_forever', 0),
        })
    return results


def sync_profile_library(profile):
    """Синхронизирует библиотеку пользователя Profile с данными из Steam.

    Возвращает кортеж: (success: bool, count: int, error_message: str | None)
    """
    if not profile.steam_id:
        return False, 0, 'Steam-аккаунт не привязан.'

    games = fetch_user_library(profile.steam_id)
    if games is None:
        return (
            False,
            0,
            'Не удалось получить игры из Steam. Убедитесь, что в настройках приватности Steam ваш профиль и доступ к играм открыты.',
        )

    from .models import LibraryGame

    existing_games = {g.steam_app_id: g for g in profile.library.all()}
    seen_app_ids = {item['steam_app_id'] for item in games}

    # Кэш обложек из уже созданных игр каталога
    catalog_headers = dict(
        Game.objects.filter(steam_app_id__in=seen_app_ids)
        .exclude(header_image='')
        .values_list('steam_app_id', 'header_image')
    )

    to_create = []
    to_update = []

    for item in games:
        app_id = item['steam_app_id']
        name = item['name']
        playtime = item['playtime_minutes']

        header_image = catalog_headers.get(app_id, '')

        if app_id in existing_games:
            game = existing_games[app_id]
            changed = False
            if name and game.name != name:
                game.name = name
                changed = True
            if game.playtime_minutes != playtime:
                game.playtime_minutes = playtime
                changed = True

            # Если обложка отсутствует — пробуем взять из каталога или подтянуть из Steam
            if not game.header_image:
                if not header_image:
                    details = fetch_app_details(app_id)
                    if details and details.get('header_image'):
                        header_image = details['header_image']
                if header_image:
                    game.header_image = header_image
                    changed = True

            if changed:
                to_update.append(game)
        else:
            # Новая игра в библиотеке
            if not header_image:
                details = fetch_app_details(app_id)
                if details and details.get('header_image'):
                    header_image = details['header_image']

            to_create.append(
                LibraryGame(
                    profile=profile,
                    steam_app_id=app_id,
                    name=name,
                    playtime_minutes=playtime,
                    header_image=header_image,
                )
            )

    if to_create:
        LibraryGame.objects.bulk_create(to_create, ignore_conflicts=True)
    if to_update:
        LibraryGame.objects.bulk_update(to_update, ['name', 'playtime_minutes', 'header_image'])

    # Удаляем игры, которых больше нет в библиотеке Steam
    profile.library.exclude(steam_app_id__in=seen_app_ids).delete()

    return True, len(games), None
