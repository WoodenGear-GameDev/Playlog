from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone

from .models import Category
from .steam_service import fetch_app_details

FIELD_LABELS = {
    'title': 'название',
    'description': 'описание',
    'release_date': 'дата выхода',
    'header_image': 'обложка',
}


@dataclass
class SyncResult:
    ok: bool
    changed: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    error: str = ''

    def __bool__(self):
        return self.ok


def _clean(name, value):
    """Проверенное значение поля либо None, если Steam его не прислал или оно непригодно."""
    if name == 'release_date':
        return value if isinstance(value, date) else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if name == 'title':
        return value[:200]
    if name == 'header_image':
        if len(value) > 500 or not value.startswith(('http://', 'https://')):
            return None
    return value


def sync_game(game, overwrite=False):
    """Заполняет поля игры данными из Steam.

    Меняются только поля, которые Steam прислал и которые непустые.
    overwrite=False: заполняются только пустые поля (при создании игры).
    overwrite=True: присланные значения заменяют прежние (кнопка «Обновить»).
    """
    try:
        data = fetch_app_details(game.steam_app_id)
    except Exception:
        return SyncResult(False, error='Steam не ответил. Попробуйте позже.')
    if not data:
        return SyncResult(False, error='Steam не вернул данных об этой игре.')

    changed, missing, update_fields = [], [], []
    for name, label in FIELD_LABELS.items():
        value = _clean(name, data.get(name))
        if value is None:
            missing.append(label)
            continue
        current = getattr(game, name)
        if value != current and (overwrite or not current):
            setattr(game, name, value)
            update_fields.append(name)
            changed.append(label)

    raw_names = data.get('categories') or []
    names = list(dict.fromkeys(
        n.strip()[:100] for n in raw_names if isinstance(n, str) and n.strip()
    ))

    with transaction.atomic():
        game.steam_synced_at = timezone.now()
        game.save(update_fields=update_fields + ['steam_synced_at'])

        if not names:
            missing.append('категории')
        elif overwrite or not game.categories.exists():
            new = [Category.objects.get_or_create(name=n)[0] for n in names]
            old_ids = set(game.categories.values_list('pk', flat=True))
            if {c.pk for c in new} != old_ids:
                game.categories.set(new)
                changed.append('категории')

    return SyncResult(True, changed=changed, missing=missing)


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