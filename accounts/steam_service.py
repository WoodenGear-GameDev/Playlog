import logging
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from catalog.models import Game, UserAchievement
from catalog.steam_service import (
    SteamAPIError,
    SteamPrivacyError,
    fetch_player_unlocked_achievements,
    steam_get,
)
from .models import LibraryGame, SteamAccount, SteamLibrary

logger = logging.getLogger(__name__)

STEAM_OWNED_GAMES_URL = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/'
STEAM_TOP_ACHIEVEMENTS_URL = 'https://api.steampowered.com/IPlayerService/GetTopAchievementsForGames/v1/'
COOLDOWN_SECONDS = 120


def fetch_games_achievement_counts(steam_id: str, app_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Запрашивает число выбитых и общее количество достижений для списка игр ОДНИМ пакетным запросом.

    Возвращает словарь: {app_id: (unlocked_count, total_count)}
    """
    if not steam_id or not app_ids:
        return {}

    api_key = getattr(settings, 'STEAM_API_KEY', '')
    if not api_key:
        return {}

    results = {}
    chunk_size = 100
    for i in range(0, len(app_ids), chunk_size):
        chunk = app_ids[i:i + chunk_size]
        params = {
            'key': api_key,
            'steamid': steam_id,
            'max_achievements': 1000,
        }
        for idx, aid in enumerate(chunk):
            params[f'appids[{idx}]'] = aid

        try:
            res = steam_get(STEAM_TOP_ACHIEVEMENTS_URL, params=params, timeout=10)
            if res.status_code == 200:
                games_data = res.json().get('response', {}).get('games', [])
                for g in games_data:
                    aid = g.get('appid')
                    if aid:
                        total = g.get('total_achievements', 0)
                        unlocked = len(g.get('achievements', []))
                        results[aid] = (unlocked, total)
        except Exception as e:
            logger.warning('Failed to fetch batch achievement counts: %s', e)

    return results


def fetch_user_library(steam_id: str) -> list[dict]:
    """Запрашивает список купленных/сыгранных игр пользователя из Steam Web API.

    Выполняет ровно ОДИН HTTP-запрос к GetOwnedGames.
    Выбрасывает SteamAPIError или SteamPrivacyError при ошибке.
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
        'include_extended_appinfo': 1,
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
        raise SteamPrivacyError(
            'Steam вернул пустой список игр. Убедитесь, что в настройках приватности Steam ваш профиль и доступ к играм открыты.'
        )

    results = []
    for item in games_data:
        appid = item.get('appid')
        if not appid:
            continue
        capsule = (item.get('capsule_filename') or '').strip().lstrip('/')
        if capsule:
            cover_url = f'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{capsule}'
        else:
            cover_url = f'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg'
        results.append({
            'steam_app_id': appid,
            'name': item.get('name', ''),
            'playtime_minutes': item.get('playtime_forever', 0),
            'cover_url': cover_url,
        })
    return results


def sync_steam_account_library(library: SteamLibrary, force: bool = False):
    """Синхронизирует библиотеку SteamLibrary (ровно 1 запрос к Steam API).

    Проверяет кулдаун 120 сек по last_attempt_at, ставит status=SYNCING,
    запрашивает GetOwnedGames, обновляет LibraryGame, выставляет status=SUCCESS/PRIVATE/ERROR,
    total_games, error_message.
    Возвращает кортеж: (success: bool, count: int, error_message: str | None)
    """
    if isinstance(library, SteamAccount):
        library = getattr(library, 'library', None) or SteamLibrary.objects.get_or_create(steam_account=library)[0]

    steam_account = library.steam_account
    if not steam_account or not steam_account.steam_id:
        return False, 0, 'Steam-аккаунт не привязан.'

    now = timezone.now()
    if not force and library.status != SteamLibrary.Status.NOT_SYNCED and library.last_attempt_at:
        elapsed = (now - library.last_attempt_at).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - elapsed)
            return False, library.total_games, f'Синхронизация уже запрашивалась. Подождите {remaining} сек. перед повторной попыткой.'

    library.status = SteamLibrary.Status.SYNCING
    library.last_attempt_at = now
    library.save(update_fields=['status', 'last_attempt_at'])

    try:
        games = fetch_user_library(steam_account.steam_id)
    except SteamPrivacyError as e:
        logger.warning('Privacy restriction syncing Steam library for %s: %s', steam_account.steam_id, e)
        library.status = SteamLibrary.Status.PRIVATE
        library.error_message = str(e)
        library.save(update_fields=['status', 'error_message'])
        return False, 0, str(e)
    except SteamAPIError as e:
        logger.error('Failed to sync Steam library for %s: %s', steam_account.steam_id, e)
        library.status = SteamLibrary.Status.ERROR
        library.error_message = str(e)
        library.save(update_fields=['status', 'error_message'])
        return False, 0, str(e)

    seen_app_ids = {item['steam_app_id'] for item in games}
    existing_games = {g.steam_app_id: g for g in library.games.all()}

    # Сопоставляем игры из каталога Playlog за один запрос
    catalog_map = {
        g.steam_app_id: g
        for g in Game.objects.filter(steam_app_id__in=seen_app_ids)
    }

    # Получаем количество выбитых и общее число достижений ОДНИМ пакетным запросом
    ach_counts = fetch_games_achievement_counts(steam_account.steam_id, list(seen_app_ids))

    to_create = []
    to_update = []

    for item in games:
        app_id = item['steam_app_id']
        name = item['name']
        playtime = item['playtime_minutes']
        cat_game = catalog_map.get(app_id)
        cover_url = item.get('cover_url') or f'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg'
        header_img = cat_game.header_image if (cat_game and cat_game.header_image) else cover_url

        ach_unlocked, ach_total = ach_counts.get(app_id, (0, 0))
        default_ach_status = (
            LibraryGame.AchievementStatus.NOT_SYNCED if ach_total > 0
            else LibraryGame.AchievementStatus.NO_ACHIEVEMENTS
        )

        if app_id in existing_games:
            lib_game = existing_games[app_id]
            changed = False
            if name and lib_game.name != name:
                lib_game.name = name
                changed = True
            if lib_game.playtime_minutes != playtime:
                lib_game.playtime_minutes = playtime
                changed = True
            if header_img and lib_game.header_image != header_img:
                lib_game.header_image = header_img
                changed = True
            if ach_total > 0:
                if lib_game.achievements_total != ach_total:
                    lib_game.achievements_total = ach_total
                    changed = True
                if lib_game.achievements_unlocked != ach_unlocked:
                    lib_game.achievements_unlocked = ach_unlocked
                    changed = True
                if lib_game.achievement_status in (LibraryGame.AchievementStatus.NO_ACHIEVEMENTS, ''):
                    lib_game.achievement_status = LibraryGame.AchievementStatus.NOT_SYNCED
                    changed = True
            elif ach_total == 0 and lib_game.achievement_status != LibraryGame.AchievementStatus.NO_ACHIEVEMENTS:
                lib_game.achievement_status = LibraryGame.AchievementStatus.NO_ACHIEVEMENTS
                lib_game.achievements_total = 0
                lib_game.achievements_unlocked = 0
                changed = True
            if changed:
                to_update.append(lib_game)
        else:
            to_create.append(
                LibraryGame(
                    library=library,
                    steam_app_id=app_id,
                    name=name,
                    playtime_minutes=playtime,
                    header_image=header_img,
                    achievements_unlocked=ach_unlocked,
                    achievements_total=ach_total,
                    achievement_status=default_ach_status,
                )
            )

    with transaction.atomic():
        if to_create:
            LibraryGame.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            LibraryGame.objects.bulk_update(
                to_update,
                ['name', 'playtime_minutes', 'header_image', 'achievements_unlocked', 'achievements_total', 'achievement_status'],
            )
        # Удаляем игры, которые пользователь убрал из Steam
        library.games.exclude(steam_app_id__in=seen_app_ids).delete()

        library.status = SteamLibrary.Status.SUCCESS
        library.total_games = len(games)
        library.error_message = ''
        library.save(update_fields=['status', 'total_games', 'error_message'])

    logger.info('Library synced for SteamAccount %s (%s): %d games', steam_account.steam_id, steam_account.user.username, len(games))
    return True, len(games), None


def sync_user_game_achievements(steam_account: SteamAccount, steam_app_id: int):
    """Синхронизирует достижения пользователя для КОНКРЕТНОЙ игры (ровно 1 точечный запрос).

    Возвращает кортеж: (success: bool, unlocked_count: int, total_count: int, status: str, error_msg: str | None)
    """
    if not steam_account or not steam_account.steam_id:
        return False, 0, 0, LibraryGame.AchievementStatus.ERROR, 'Steam-аккаунт не привязан.'

    library = getattr(steam_account, 'library', None)
    lib_entry = library.games.filter(steam_app_id=steam_app_id).first() if library else None
    cat_game = Game.objects.filter(steam_app_id=steam_app_id).first()

    now = timezone.now()
    try:
        unlocked_map, total_count, is_private = fetch_player_unlocked_achievements(
            steam_account.steam_id, steam_app_id
        )
    except SteamPrivacyError:
        if lib_entry:
            lib_entry.achievement_status = LibraryGame.AchievementStatus.PRIVATE
            lib_entry.error_message = 'Статистика скрыта настройками приватности Steam.'
            lib_entry.last_attempt_at = now
            lib_entry.save(update_fields=['achievement_status', 'error_message', 'last_attempt_at'])
        return False, 0, 0, LibraryGame.AchievementStatus.PRIVATE, 'Статистика скрыта настройками приватности Steam.'
    except SteamAPIError as e:
        logger.error('Failed to fetch player achievements for %s on app %s: %s', steam_account.steam_id, steam_app_id, e)
        if lib_entry:
            lib_entry.achievement_status = LibraryGame.AchievementStatus.ERROR
            lib_entry.error_message = str(e)
            lib_entry.last_attempt_at = now
            lib_entry.save(update_fields=['achievement_status', 'error_message', 'last_attempt_at'])
        return False, 0, 0, LibraryGame.AchievementStatus.ERROR, str(e)

    if is_private:
        if lib_entry:
            lib_entry.achievement_status = LibraryGame.AchievementStatus.PRIVATE
            lib_entry.error_message = 'Статистика скрыта настройками приватности Steam.'
            lib_entry.last_attempt_at = now
            lib_entry.save(update_fields=['achievement_status', 'error_message', 'last_attempt_at'])
        return False, 0, 0, LibraryGame.AchievementStatus.PRIVATE, 'Статистика скрыта настройками приватности Steam.'

    if total_count == 0:
        if lib_entry:
            lib_entry.achievement_status = LibraryGame.AchievementStatus.NO_ACHIEVEMENTS
            lib_entry.achievements_total = 0
            lib_entry.achievements_unlocked = 0
            lib_entry.error_message = ''
            lib_entry.last_attempt_at = now
            lib_entry.save(update_fields=['achievement_status', 'achievements_total', 'achievements_unlocked', 'error_message', 'last_attempt_at'])
        return True, 0, 0, LibraryGame.AchievementStatus.NO_ACHIEVEMENTS, None

    unlocked_count = len(unlocked_map)

    with transaction.atomic():
        if cat_game:
            # Обновляем выбитые ачивки в UserAchievement с точным временем получения
            matched_achs = list(cat_game.achievements.filter(api_name__in=unlocked_map.keys()))
            matched_ids = {a.pk for a in matched_achs}

            # Удаляем те, которые больше не выбиты
            UserAchievement.objects.filter(
                steam_account=steam_account,
                achievement__game=cat_game,
            ).exclude(achievement_id__in=matched_ids).delete()

            # Создаем или обновляем с временем получения unlocked_at
            for ach in matched_achs:
                unlocked_at = unlocked_map.get(ach.api_name)
                UserAchievement.objects.update_or_create(
                    steam_account=steam_account,
                    achievement=ach,
                    defaults={'unlocked_at': unlocked_at},
                )

        if lib_entry:
            lib_entry.achievement_status = LibraryGame.AchievementStatus.SYNCED
            lib_entry.achievements_unlocked = unlocked_count
            lib_entry.achievements_total = total_count
            lib_entry.error_message = ''
            lib_entry.last_attempt_at = now
            lib_entry.save(update_fields=['achievement_status', 'achievements_unlocked', 'achievements_total', 'error_message', 'last_attempt_at'])

    return True, unlocked_count, total_count, LibraryGame.AchievementStatus.SYNCED, None
