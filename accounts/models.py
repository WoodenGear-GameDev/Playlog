from django.conf import settings
from django.db import models
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def avatar_upload_path(instance, filename):
    # Имя файла заменяем на случайное: так не бывает конфликтов имён
    # и проблем с русскими символами или пробелами
    return f'avatars/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Пользователь',
    )
    steam_id = models.CharField('SteamID64', max_length=17, blank=True)
    avatar = models.ImageField(
    'Аватар', upload_to=avatar_upload_path, blank=True
    )

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'
        constraints = [
            models.UniqueConstraint(
                fields=['steam_id'],
                condition=~models.Q(steam_id=''),
                name='unique_nonempty_steam_id',
            ),
        ]

    def __str__(self):
        return f'Профиль {self.user.username}'

class LibraryGame(models.Model):
    """Игра из библиотеки Steam пользователя.

    Сейчас заполняется вручную через админку. Позже библиотеку будет
    загружать код синхронизации со Steam (отдельная задача).
    """

    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name='library',
        verbose_name='Профиль',
    )
    steam_app_id = models.PositiveIntegerField('Steam AppID')
    name = models.CharField('Название', max_length=200, blank=True)
    playtime_minutes = models.PositiveIntegerField('Время в игре (мин)', default=0)

    class Meta:
        verbose_name = 'Игра в библиотеке'
        verbose_name_plural = 'Библиотека'
        ordering = ['-playtime_minutes', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['profile', 'steam_app_id'],
                name='unique_library_game_per_profile',
            ),
        ]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.name or f'Steam app {self.steam_app_id}'

    @property
    def playtime_hours(self):
        return round(self.playtime_minutes / 60, 1)