import datetime
import logging
import requests

logger = logging.getLogger(__name__)

STEAM_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

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
        response = requests.get(url, params=params, headers=STEAM_HEADERS, timeout=10)
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
        response = requests.get(url, params=params, headers=STEAM_HEADERS, timeout=5)
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
