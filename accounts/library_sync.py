import math
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import LibraryGame, Profile
from .steam_library import ProfilePrivate, SteamLibraryError, fetch_owned_games

COOLDOWN_SECONDS = 120
MAX_APP_ID = 2_147_483_647
BATCH = 500


class LibrarySyncError(Exception):
    """Ошибка с текстом, который можно показать пользователю."""


def cooldown_left(profile):
    """Сколько секунд осталось до следующего запроса (0, если можно)."""
    last = profile.library_sync_requested_at
    if not last:
        return 0
    left = COOLDOWN_SECONDS - (timezone.now() - last).total_seconds()
    return max(0, math.ceil(left))


def _clean_entries(raw):
    """Проверенные записи {steam_app_id: {'name': str, 'minutes': int | None}}."""
    cleaned = {}
    for item in raw or []:
        try:
            app_id = int(item.get('steam_app_id'))
        except (AttributeError, TypeError, ValueError):
            continue
        if not 0 < app_id <= MAX_APP_ID:
            continue
        name = item.get('name')
        name = name.strip()[:200] if isinstance(name, str) else ''
        try:
            minutes = int(item.get('playtime_minutes'))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None and minutes < 0:
            minutes = None
        cleaned[app_id] = {'name': name, 'minutes': minutes}
    return cleaned


def sync_library(profile):
    """Обновляет библиотеку профиля из Steam. Возвращает счётчики изменений.

    Бросает LibrarySyncError с понятным текстом.
    """
    if not profile.steam_id:
        raise LibrarySyncError('Сначала привяжите аккаунт Steam.')

    # Занимаем «окно» запроса одной атомарной командой: двойной клик
    # или два параллельных запроса не запустят загрузку дважды
    now = timezone.now()
    border = now - timedelta(seconds=COOLDOWN_SECONDS)
    acquired = (
        Profile.objects.filter(pk=profile.pk)
        .filter(
            Q(library_sync_requested_at__isnull=True)
            | Q(library_sync_requested_at__lt=border)
        )
        .update(library_sync_requested_at=now)
    )
    if not acquired:
        profile.refresh_from_db()
        raise LibrarySyncError(
            f'Обновлять библиотеку можно не чаще раза в {COOLDOWN_SECONDS // 60} мин. '
            f'Попробуйте через {cooldown_left(profile)} с.'
        )

    try:
        raw = fetch_owned_games(profile.steam_id)
    except ProfilePrivate as exc:
        raise LibrarySyncError(
            str(exc) or 'Steam скрывает список ваших игр. Сделайте его публичным '
            'в настройках приватности Steam и повторите.'
        )
    except SteamLibraryError as exc:
        raise LibrarySyncError(str(exc) or 'Не удалось получить данные из Steam.')
    except Exception:
        raise LibrarySyncError('Не удалось получить данные из Steam. Попробуйте позже.')

    entries = _clean_entries(raw)
    if not entries:
        # Закрытый профиль или пустая библиотека: уже загруженное не удаляем
        Profile.objects.filter(pk=profile.pk).update(library_synced_at=now)
        return {'added': 0, 'updated': 0, 'removed': 0, 'empty': True}

    with transaction.atomic():
        existing = {g.steam_app_id: g for g in profile.library.all()}
        to_create, to_update = [], []
        for app_id, data in entries.items():
            current = existing.get(app_id)
            if current is None:
                to_create.append(LibraryGame(
                    profile=profile,
                    steam_app_id=app_id,
                    name=data['name'],
                    playtime_minutes=data['minutes'] or 0,
                ))
                continue
            changed = False
            # Название или время, которые Steam не прислал, не затираем
            if data['name'] and data['name'] != current.name:
                current.name = data['name']
                changed = True
            if data['minutes'] is not None and data['minutes'] != current.playtime_minutes:
                current.playtime_minutes = data['minutes']
                changed = True
            if changed:
                to_update.append(current)

        stale = [g.pk for app_id, g in existing.items() if app_id not in entries]

        LibraryGame.objects.bulk_create(to_create, batch_size=BATCH)
        LibraryGame.objects.bulk_update(
            to_update, ['name', 'playtime_minutes'], batch_size=BATCH
        )
        for i in range(0, len(stale), BATCH):
            LibraryGame.objects.filter(pk__in=stale[i:i + BATCH]).delete()

        Profile.objects.filter(pk=profile.pk).update(library_synced_at=now)

    return {
        'added': len(to_create),
        'updated': len(to_update),
        'removed': len(stale),
        'empty': False,
    }


def describe_stats(stats):
    if stats['empty']:
        return 'Steam вернул пустой список игр. Ваша библиотека на сайте не изменена.'
    parts = []
    if stats['added']:
        parts.append(f"добавлено: {stats['added']}")
    if stats['updated']:
        parts.append(f"обновлено: {stats['updated']}")
    if stats['removed']:
        parts.append(f"удалено: {stats['removed']}")
    if not parts:
        return 'Библиотека уже актуальна.'
    return 'Библиотека обновлена (' + ', '.join(parts) + ').'