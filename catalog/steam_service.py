import datetime
import logging
import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

SCHEMA_CACHE_TTL = 86400  # 24 часа для неизменяемой схемы ачивок
PLAYER_ACH_CACHE_TTL = 600  # 10 минут для статуса выбитых ачивок игрока

STEAM_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

_steam_session = None


def get_steam_session() -> requests.Session:
    """Возвращает единую сессию requests с настроенными заголовками Steam."""
    global _steam_session
    if _steam_session is None:
        _steam_session = requests.Session()
        _steam_session.headers.update(STEAM_HEADERS)
    return _steam_session


def steam_get(url: str, params=None, timeout: int = 5) -> requests.Response:
    """Централизованный GET-запрос к API Steam с единой сессией, заголовками и таймаутом."""
    return get_steam_session().get(url, params=params, timeout=timeout)

MONTHS = {
    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'мая': 5,
    'июн': 6, 'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def _parse_release_date(raw_date: str) -> datetime.date | None:
    if not raw_date:
        return None
    cleaned = raw_date.lower().replace('г.', '').replace(',', '').strip()
    parts = cleaned.split()
    day, month, year = None, None, None
    for p in parts:
        if p.isdigit():
            val = int(p)
            if val > 1970:
                year = val
            elif not day and 1 <= val <= 31:
                day = val
        else:
            for k, m in MONTHS.items():
                if p.startswith(k):
                    month = m
                    break
    if year and month and day:
        try:
            return datetime.date(year, month, day)
        except ValueError:
            pass
    if year and month:
        return datetime.date(year, month, 1)
    if year:
        return datetime.date(year, 1, 1)
    return None


def fetch_app_details(app_id):
    """Запрашивает данные об игре из Steam Store API."""
    url = 'https://store.steampowered.com/api/appdetails'
    params = {'appids': app_id, 'l': 'russian', 'cc': 'ru'}
    try:
        response = steam_get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning('Failed to fetch Steam app details for %s: %s', app_id, e)
        return None

    app_data = data.get(str(app_id), {})
    if not app_data.get('success'):
        return None

    game_info = app_data.get('data', {})
    raw_date = game_info.get('release_date', {}).get('date', '')

    genres = [
        g['description']
        for g in game_info.get('genres', [])
        if 'description' in g
    ]

    return {
        'title': game_info.get('name', ''),
        'description': game_info.get('short_description', '') or game_info.get('detailed_description', ''),
        'release_date': _parse_release_date(raw_date),
        'header_image': game_info.get('header_image', ''),
        'categories': genres,
    }


def search_steam_games(query: str, limit: int = 12):
    """Ищет игры в Steam Store Search API."""
    if not query or not query.strip():
        return []

    url = 'https://store.steampowered.com/api/storesearch/'
    params = {'term': query.strip(), 'l': 'russian', 'cc': 'ru'}
    try:
        response = steam_get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning('Failed to search Steam games for "%s": %s', query, e)
        return []

    items = data.get('items', [])
    results = []
    for item in items[:limit]:
        appid = item.get('id')
        name = item.get('name')
        if not appid or not name:
            continue
        results.append({
            'steam_app_id': appid,
            'title': name,
            'header_image': item.get('tiny_image', ''),
        })
    return results


def fetch_player_achievement_counts(steam_id: str, app_id: int):
    """Возвращает (unlocked, total, is_private) для игры.

    Если профиль закрыт (403), is_private=True, чтобы не спамить запросами для остальных игр.
    """
    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key:
        return 0, 0, False

    url_player = 'https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/'
    try:
        res = steam_get(
            url_player,
            params={'key': api_key, 'steamid': steam_id, 'appid': app_id},
            timeout=4,
        )
        if res.status_code == 403:
            return 0, 0, True
        if res.status_code == 200:
            stats = res.json().get('playerstats', {})
            if stats.get('success'):
                achievements = stats.get('achievements', [])
                total = len(achievements)
                unlocked = sum(1 for a in achievements if a.get('achieved') == 1)
                return unlocked, total, False
    except Exception as e:
        logger.warning('Failed to fetch player achievement counts for %s/%s: %s', steam_id, app_id, e)

    return 0, 0, False


def fetch_game_achievements(app_id, steam_id=None):
    """Возвращает информацию о достижениях игры из Steam с кэшированием.

    Если передан steam_id, помечает выбитые пользователем ачивки.
    """
    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key:
        return {'total': 0, 'unlocked': 0, 'has_player_stats': False, 'items': []}

    schema_cache_key = f'steam_schema_achievements_{app_id}'
    raw_schema = cache.get(schema_cache_key)

    if raw_schema is None:
        url_schema = 'https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/'
        try:
            res = steam_get(
                url_schema,
                params={'key': api_key, 'appid': app_id, 'l': 'russian'},
                timeout=5,
            )
            if res.status_code == 200:
                raw_schema = (
                    res.json()
                    .get('game', {})
                    .get('availableGameStats', {})
                    .get('achievements', [])
                )
                if raw_schema:
                    cache.set(schema_cache_key, raw_schema, SCHEMA_CACHE_TTL)
        except Exception as e:
            logger.warning('Failed to fetch schema achievements for %s: %s', app_id, e)

    if not raw_schema:
        return {'total': 0, 'unlocked': 0, 'has_player_stats': False, 'items': []}

    unlocked_names = set()
    has_player_stats = False
    if steam_id:
        player_cache_key = f'steam_player_ach_{app_id}_{steam_id}'
        cached_player = cache.get(player_cache_key)
        if cached_player is not None:
            has_player_stats, unlocked_names = cached_player
        else:
            url_player = 'https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/'
            try:
                res_player = steam_get(
                    url_player,
                    params={'key': api_key, 'steamid': steam_id, 'appid': app_id, 'l': 'russian'},
                    timeout=5,
                )
                if res_player.status_code == 200:
                    stats = res_player.json().get('playerstats', {})
                    if stats.get('success'):
                        has_player_stats = True
                        unlocked_names = {
                            a['apiname']
                            for a in stats.get('achievements', [])
                            if a.get('achieved') == 1
                        }
                        cache.set(player_cache_key, (has_player_stats, unlocked_names), PLAYER_ACH_CACHE_TTL)
            except Exception as e:
                logger.warning('Failed to fetch player achievements for %s/%s: %s', app_id, steam_id, e)

    items = []
    for a in raw_schema:
        api_name = a.get('name')
        achieved = api_name in unlocked_names
        items.append({
            'name': a.get('displayName') or api_name,
            'description': a.get('description', ''),
            'icon': a.get('icon', ''),
            'icongray': a.get('icongray') or a.get('icon', ''),
            'achieved': achieved,
        })

    return {
        'total': len(items),
        'unlocked': len(unlocked_names),
        'has_player_stats': has_player_stats,
        'items': items,
    }

