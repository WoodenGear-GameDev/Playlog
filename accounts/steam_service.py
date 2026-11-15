import logging
import requests
from django.conf import settings
from django.db import transaction

from catalog.models import Achievement, Game
from catalog.steam_service import (
    SteamAPIError,
    SteamPrivacyError,
    fetch_app_details,
    fetch_player_unlocked_achievements,
    steam_get,
)

logger = logging.getLogger(__name__)

STEAM_OWNED_GAMES_URL = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/'


def fetch_user_library(steam_id: str):
    """Запрашивает список купленных/сыгранных игр пользователя из Steam Web API.

    Выбрасывает SteamAPIError при любой ошибке.
    """
    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key:
        raise SteamAPIError('В настройках сервера не задан STEAM_API_KEY.')
    if not steam_id:
        raise SteamAPIError('Не указан Steam ID пользователя.')

    params = {
        'key': api_key,
        'steamid': steam_id,
        'include_appinfo': 1,
        'include_played_free_games': 1,
        'format': 'json',
    }

    response = steam_get(
        STEAM_OWNED_GAMES_URL,
        params=params,
        timeout=10,
    )
    data = response.json()

    games_data = data.get('response', {}).get('games')
    if games_data is None:
        raise SteamPrivacyError('Steam вернул пустой список игр. Убедитесь, что в настройках приватности Steam ваш профиль и доступ к играм открыты.')

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

    try:
        games = fetch_user_library(profile.steam_id)
    except SteamAPIError as e:
        logger.error('Failed to sync profile library for %s: %s', profile.steam_id, e)
        return False, 0, str(e)

    from .models import LibraryGame

    existing_games = {g.steam_app_id: g for g in profile.library.all()}
    seen_app_ids = {item['steam_app_id'] for item in games}

    catalog_headers = dict(
        Game.objects.filter(steam_app_id__in=seen_app_ids)
        .exclude(header_image='')
        .values_list('steam_app_id', 'header_image')
    )

    to_create = []
    to_update = []
    stats_private = False

    for item in games:
        app_id = item['steam_app_id']
        name = item['name']
        playtime = item['playtime_minutes']
        header_image = catalog_headers.get(app_id, '')

        unlocked_set, ach_total = set(), 0
        if not stats_private:
            try:
                unlocked_set, ach_total, is_private = fetch_player_unlocked_achievements(
                    profile.steam_id, app_id
                )
                if is_private:
                    stats_private = True
            except SteamAPIError as e:
                logger.warning('Failed to fetch achievements for app %s during library sync: %s', app_id, e)

        ach_unlocked = len(unlocked_set)

        if unlocked_set:
            user_achs = Achievement.objects.filter(
                game__steam_app_id=app_id, api_name__in=unlocked_set
            )
            if user_achs.exists():
                profile.unlocked_achievements.add(*user_achs)

        if app_id in existing_games:
            game = existing_games[app_id]
            changed = False
            if name and game.name != name:
                game.name = name
                changed = True
            if game.playtime_minutes != playtime:
                game.playtime_minutes = playtime
                changed = True

            if not game.header_image and header_image:
                game.header_image = header_image
                changed = True

            if ach_total > 0:
                if game.achievements_total != ach_total:
                    game.achievements_total = ach_total
                    changed = True
                if game.achievements_unlocked != ach_unlocked:
                    game.achievements_unlocked = ach_unlocked
                    changed = True

            if changed:
                to_update.append(game)
        else:
            to_create.append(
                LibraryGame(
                    profile=profile,
                    steam_app_id=app_id,
                    name=name,
                    playtime_minutes=playtime,
                    header_image=header_image,
                    achievements_total=ach_total,
                    achievements_unlocked=ach_unlocked,
                )
            )

    with transaction.atomic():
        if to_create:
            LibraryGame.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            LibraryGame.objects.bulk_update(
                to_update,
                ['name', 'playtime_minutes', 'header_image', 'achievements_total', 'achievements_unlocked'],
            )
        profile.library.exclude(steam_app_id__in=seen_app_ids).delete()

    warning_msg = None
    if stats_private:
        warning_msg = 'Библиотека синхронизирована, но доступ к достижениям скрыт в настройках приватности Steam.'

    logger.info('Library synced for profile %s: %d games', profile.user.username, len(games))
    return True, len(games), warning_msg
