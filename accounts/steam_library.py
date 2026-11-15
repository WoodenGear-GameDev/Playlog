from catalog.steam_service import SteamAPIError, SteamPrivacyError
from .steam_service import fetch_user_library


class SteamLibraryError(Exception):
    """Общая ошибка загрузки библиотеки."""


class ProfilePrivate(SteamLibraryError):
    """Steam скрыл список игр настройками приватности."""


class SteamUnavailable(SteamLibraryError):
    """Steam не ответил, вернул ошибку или отклонил запрос."""


def fetch_owned_games(steam_id):
    """Запрашивает список игр пользователя из Steam Web API.

    Вход: подтверждённый SteamID64 (строка из 17 цифр).
    Возвращает список словарей:
    [{'steam_app_id': 620, 'name': 'Portal 2', 'playtime_minutes': 1234}, ...]
    """
    try:
        return fetch_user_library(steam_id)
    except SteamPrivacyError as exc:
        raise ProfilePrivate(str(exc))
    except SteamAPIError as exc:
        raise SteamUnavailable(str(exc))
    except Exception as exc:
        raise SteamUnavailable('Не удалось связаться со Steam. Попробуйте позже.')
