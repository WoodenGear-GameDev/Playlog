import datetime
import logging
import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

STEAM_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

_steam_session = None


class SteamAPIError(Exception):
    """Базовая ошибка при работе со Steam API."""
    pass


class SteamConnectionError(SteamAPIError):
    """Ошибка сети, таймаута или сброса SSL-соединения серверами Steam."""
    pass


class SteamRateLimitError(SteamAPIError):
    """Превышение лимита запросов Steam API (HTTP 429)."""
    pass


class SteamPrivacyError(SteamAPIError):
    """Данные скрыты настройками приватности профиля Steam (HTTP 403)."""
    pass


class SteamDataValidationError(SteamAPIError):
    """Неполные, пустые или невалидные данные, полученные от Steam."""
    pass


def get_steam_session() -> requests.Session:
    """Возвращает единую сессию requests с настроенными заголовками Steam."""
    global _steam_session
    if _steam_session is None:
        _steam_session = requests.Session()
        _steam_session.headers.update(STEAM_HEADERS)
    return _steam_session


def steam_get(url: str, params=None, timeout: int = 10) -> requests.Response:
    """Централизованный GET-запрос к API Steam с единой сессией, заголовками и строгой обработкой ошибок."""
    try:
        response = get_steam_session().get(url, params=params, timeout=timeout)
    except requests.exceptions.Timeout as e:
        logger.error('Steam API request timed out for %s: %s', url, e)
        raise SteamConnectionError('Серверы Steam не ответили вовремя (таймаут соединения). Попробуйте позже.') from e
    except requests.exceptions.SSLError as e:
        logger.error('Steam API SSL error for %s: %s', url, e)
        raise SteamConnectionError('Сбой защищённого соединения со Steam (SSL error). Серверы Steam сбросили подключение.') from e
    except requests.exceptions.ConnectionError as e:
        logger.error('Steam API connection error for %s: %s', url, e)
        raise SteamConnectionError('Не удалось подключиться к серверам Steam. Проверьте интернет-соединение.') from e
    except requests.exceptions.RequestException as e:
        logger.error('Steam API request failed for %s: %s', url, e)
        raise SteamConnectionError(f'Сетевая ошибка при обращении к Steam: {e}') from e

    if response.status_code == 429:
        logger.error('Steam API rate limit exceeded (HTTP 429) for %s', url)
        raise SteamRateLimitError('Превышен лимит запросов к серверам Steam. Пожалуйста, подождите минуту перед следующим действием.')

    if response.status_code == 403:
        logger.error('Steam API forbidden (HTTP 403) for %s: %s', url, response.text[:200])
        raise SteamPrivacyError('Доступ к данным закрыт настройками приватности Steam (HTTP 403).')

    if response.status_code >= 500:
        logger.error('Steam API server error (HTTP %s) for %s: %s', response.status_code, url, response.text[:200])
        raise SteamConnectionError(f'Серверы Steam временно недоступны (ошибка {response.status_code}). Попробуйте позже.')

    return response


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


def fetch_app_details(app_id: int):
    """Запрашивает полные валидные данные об игре из Steam Store API.

    Выбрасывает SteamAPIError при любой ошибке или неполных данных.
    """
    url = 'https://store.steampowered.com/api/appdetails'
    params = {'appids': app_id, 'l': 'russian', 'cc': 'ru'}

    response = steam_get(url, params=params, timeout=10)
    try:
        data = response.json()
    except Exception as e:
        logger.error('Invalid JSON from Steam Store for %s: %s', app_id, response.text[:300])
        raise SteamDataValidationError(f'Steam вернул некорректный ответ для игры с AppID {app_id}.') from e

    app_data = data.get(str(app_id), {})
    if not app_data.get('success'):
        logger.error('Steam Store returned success=False for %s: %s', app_id, app_data)
        raise SteamDataValidationError(f'Игра с AppID {app_id} не найдена в магазине Steam или недоступна в текущем регионе.')

    game_info = app_data.get('data', {})
    title = (game_info.get('name') or '').strip()
    if not title:
        raise SteamDataValidationError(f'Steam Store API не вернул название для игры с AppID {app_id}.')

    header_image = (game_info.get('header_image') or '').strip()
    if not header_image:
        raise SteamDataValidationError(f'Steam Store API не вернул обложку для игры «{title}» (AppID {app_id}).')

    raw_date = game_info.get('release_date', {}).get('date', '')
    genres = [
        g['description'].strip()
        for g in game_info.get('genres', [])
        if 'description' in g and g['description'].strip()
    ]

    description = (game_info.get('short_description') or game_info.get('detailed_description') or '').strip()

    return {
        'title': title,
        'description': description,
        'release_date': _parse_release_date(raw_date),
        'header_image': header_image,
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


def fetch_schema_achievements(app_id: int):
    """Запрашивает схему всех достижений игры из Steam Web API.

    Выбрасывает SteamAPIError при сбоях сети или ошибках Steam.
    Возвращает пустой список ТОЛЬКО если Steam подтвердил, что в игре нет достижений.
    """
    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key:
        raise SteamAPIError('На сервере не настроен STEAM_API_KEY в файле .env.')

    url = 'https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/'
    res = steam_get(
        url,
        params={'key': api_key, 'appid': app_id, 'l': 'russian'},
        timeout=8,
    )

    # 400 Bad Request возвращается для игр без поддержки статистики/ачивок
    if res.status_code == 400:
        return []

    if res.status_code != 200:
        logger.error('Steam returned status %s for GetSchemaForGame on %s: %s', res.status_code, app_id, res.text[:200])
        raise SteamAPIError(f'Steam Web API вернул код {res.status_code} при запросе достижений игры.')

    try:
        data = res.json()
    except Exception as e:
        raise SteamDataValidationError(f'Steam вернул некорректный ответ для достижений игры {app_id}.') from e

    raw_achievements = (
        data.get('game', {})
        .get('availableGameStats', {})
        .get('achievements', [])
    )
    items = []
    for a in raw_achievements:
        api_name = a.get('name')
        if not api_name:
            continue
        name = a.get('displayName') or api_name
        items.append({
            'api_name': api_name,
            'name': name,
            'description': a.get('description', '') or '',
            'icon_url': a.get('icon', '') or '',
            'icon_gray_url': a.get('icongray') or a.get('icon', '') or '',
        })
    return items


def fetch_player_unlocked_achievements(steam_id: str, app_id: int):
    """Возвращает (unlocked_set, total_count, is_private) для игрока.

    Выбрасывает SteamAPIError при сбоях сети/Steam.
    """
    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key:
        raise SteamAPIError('На сервере не настроен STEAM_API_KEY в файле .env.')
    if not steam_id:
        return set(), 0, False

    url_player = 'https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/'
    try:
        res = steam_get(
            url_player,
            params={'key': api_key, 'steamid': steam_id, 'appid': app_id},
            timeout=8,
        )
    except SteamPrivacyError:
        return set(), 0, True

    if res.status_code == 403:
        return set(), 0, True

    if res.status_code == 400:
        # У игры нет статистики/достижений
        return set(), 0, False

    if res.status_code != 200:
        logger.error('Steam returned status %s for GetPlayerAchievements on %s/%s: %s', res.status_code, steam_id, app_id, res.text[:200])
        raise SteamAPIError(f'Steam вернул код {res.status_code} при запросе достижений игрока.')

    try:
        stats = res.json().get('playerstats', {})
    except Exception as e:
        raise SteamDataValidationError(f'Steam вернул некорректный ответ для достижений игрока {steam_id}.') from e

    if not stats.get('success'):
        error_msg = stats.get('error', '')
        if 'profile is not public' in error_msg.lower():
            return set(), 0, True
        raise SteamAPIError(f'Steam не смог отдать достижения игрока: {error_msg}')

    achievements = stats.get('achievements', [])
    total = len(achievements)
    unlocked_set = {
        a['apiname']
        for a in achievements
        if a.get('achieved') == 1
    }
    return unlocked_set, total, False


def fetch_player_achievement_counts(steam_id: str, app_id: int):
    """Возвращает (unlocked, total, is_private) для игры."""
    unlocked_set, total, is_priv = fetch_player_unlocked_achievements(steam_id, app_id)
    return len(unlocked_set), total, is_priv


def fetch_global_achievement_percentages(app_id: int) -> dict[str, float]:
    """Возвращает словарь {api_name: percent_float} глобальной статистики выбивания достижений."""
    url = 'https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/'
    try:
        res = steam_get(url, params={'gameid': app_id}, timeout=8)
    except SteamPrivacyError:
        # У программ, софта или игр без публичной статистики Steam возвращает 403
        return {}

    if res.status_code in (400, 404):
        return {}

    if res.status_code != 200:
        logger.error(
            'Steam returned status %s for GetGlobalAchievementPercentages on %s: %s',
            res.status_code,
            app_id,
            res.text[:200],
        )
        raise SteamAPIError(f'Steam вернул код {res.status_code} при запросе редкости достижений.')

    try:
        data = res.json()
    except Exception as e:
        raise SteamDataValidationError(
            f'Steam вернул некорректный ответ редкости достижений игры {app_id}.'
        ) from e

    ach_list = data.get('achievementpercentages', {}).get('achievements', [])
    result = {}
    for item in ach_list:
        name = item.get('name')
        if name:
            try:
                result[name] = round(float(item.get('percent', 0.0)), 1)
            except (ValueError, TypeError):
                result[name] = 0.0
    return result


REVIEW_SCORE_DESCRIPTIONS = {
    'Overwhelmingly Positive': 'Крайне положительные',
    'Very Positive': 'Очень положительные',
    'Positive': 'Положительные',
    'Mostly Positive': 'В основном положительные',
    'Mixed': 'Смешанные',
    'Mostly Negative': 'В основном отрицательные',
    'Negative': 'Отрицательные',
    'Very Negative': 'Очень отрицательные',
    'Overwhelmingly Negative': 'Крайне отрицательные',
}


def fetch_game_review_summary(app_id: int) -> dict:
    """Запрашивает сводку пользовательских отзывов Steam (рейтинг, %, общее число)."""
    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key:
        raise SteamAPIError('На сервере не настроен STEAM_API_KEY в файле .env.')

    url = 'https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/'
    try:
        res = steam_get(url, params={'key': api_key, 'appid': app_id, 'num_per_page': 0}, timeout=8)
    except SteamPrivacyError:
        return {'desc': '', 'percent': None, 'total': 0}

    if res.status_code in (400, 404):
        return {'desc': '', 'percent': None, 'total': 0}

    if res.status_code != 200:
        logger.error(
            'Steam returned status %s for GetAppReviews on %s: %s',
            res.status_code,
            app_id,
            res.text[:200],
        )
        raise SteamAPIError(f'Steam вернул код {res.status_code} при запросе отзывов игры.')

    try:
        data = res.json().get('response', {})
    except Exception as e:
        raise SteamDataValidationError(
            f'Steam вернул некорректный ответ отзывов игры {app_id}.'
        ) from e

    qs = data.get('query_summary') or {}
    raw_desc = qs.get('review_score_desc', '')
    desc = REVIEW_SCORE_DESCRIPTIONS.get(raw_desc, raw_desc)
    total_reviews = int(qs.get('total_reviews', 0) or 0)
    total_positive = int(qs.get('total_positive', 0) or 0)

    percent = None
    if total_reviews > 0:
        percent = round((total_positive / total_reviews) * 100)

    return {
        'desc': desc,
        'percent': percent,
        'total': total_reviews,
    }


