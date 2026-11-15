from django.conf import settings
from django.db import models
import uuid
from pathlib import Path


def avatar_upload_path(instance, filename):
    return f'avatars/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class Profile(models.Model):
    """Профиль пользователя сайта Playlog (независим от внешних сервисов)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Пользователь',
    )
    avatar = models.ImageField(
        'Аватар', upload_to=avatar_upload_path, blank=True
    )

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return f'Профиль {self.user.username}'


class SteamAccount(models.Model):
    """Выделенная изолированная сущность для привязки Steam к пользователю (Steam Identity)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='steam_account',
        verbose_name='Пользователь',
    )
    steam_id = models.CharField('SteamID64', max_length=32, unique=True)
    show_steam = models.BooleanField(
        'Показывать Steam в публичном профиле', default=True
    )
    created_at = models.DateTimeField('Дата привязки', auto_now_add=True)

    class Meta:
        verbose_name = 'Аккаунт Steam'
        verbose_name_plural = 'Аккаунты Steam'

    def __str__(self):
        return f'Steam {self.steam_id} ({self.user.username})'


class SteamLibrary(models.Model):
    """Библиотека игр пользователя в Steam."""

    class Status(models.TextChoices):
        NOT_SYNCED = 'not_synced', 'Не синхронизирована'
        SYNCING = 'syncing', 'Синхронизируется'
        SUCCESS = 'success', 'Синхронизирована'
        PRIVATE = 'private', 'Профиль или игры скрыты приватностью'
        ERROR = 'error', 'Ошибка сети / API'

    steam_account = models.OneToOneField(
        SteamAccount,
        on_delete=models.CASCADE,
        related_name='library',
        verbose_name='Аккаунт Steam',
    )
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_SYNCED,
    )
    total_games = models.PositiveIntegerField('Всего игр', default=0)
    last_attempt_at = models.DateTimeField('Последняя попытка', auto_now_add=True)
    error_message = models.CharField('Ошибка', max_length=500, default='', blank=True)

    class Meta:
        verbose_name = 'Библиотека Steam'
        verbose_name_plural = 'Библиотеки Steam'

    def __str__(self):
        return f'Библиотека {self.steam_account}'


class LibraryGame(models.Model):
    """Игра из библиотеки Steam пользователя."""

    class AchievementStatus(models.TextChoices):
        NOT_SYNCED = 'not_synced', 'Не синхронизировано'
        SYNCING = 'syncing', 'Синхронизируется'
        SYNCED = 'synced', 'Синхронизировано'
        NO_ACHIEVEMENTS = 'no_achievements', 'В игре нет достижений'
        PRIVATE = 'private', 'Статистика скрыта приватностью'
        ERROR = 'error', 'Ошибка'

    library = models.ForeignKey(
        SteamLibrary,
        on_delete=models.CASCADE,
        related_name='games',
        verbose_name='Библиотека Steam',
    )
    steam_app_id = models.PositiveIntegerField('Steam AppID', db_index=True)
    name = models.CharField('Название из Steam', max_length=255, default='', blank=True)
    playtime_minutes = models.PositiveIntegerField('Время в игре (мин)', default=0)
    header_image = models.URLField('Обложка (URL)', max_length=500, default='', blank=True)

    achievement_status = models.CharField(
        'Статус достижений',
        max_length=20,
        choices=AchievementStatus.choices,
        default=AchievementStatus.NOT_SYNCED,
    )
    achievements_unlocked = models.PositiveIntegerField('Выбито достижений', default=0)
    achievements_total = models.PositiveIntegerField('Всего достижений', default=0)
    last_attempt_at = models.DateTimeField('Последняя попытка', auto_now_add=True)
    error_message = models.CharField('Ошибка', max_length=500, default='', blank=True)

    class Meta:
        verbose_name = 'Игра в библиотеке'
        verbose_name_plural = 'Игры в библиотеке'
        ordering = ['-playtime_minutes', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['library', 'steam_app_id'],
                name='unique_library_game_per_library',
            ),
        ]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.name or f'Steam app {self.steam_app_id}'

    @property
    def display_cover(self):
        cat_game = getattr(self, 'catalog_game', None)
        if cat_game and getattr(cat_game, 'header_image', None):
            return cat_game.header_image
        if self.header_image:
            return self.header_image
        return f'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{self.steam_app_id}/capsule_231x87.jpg'

    @property
    def playtime_hours(self):
        return round(self.playtime_minutes / 60, 1)

    @property
    def achievements_progress_percent(self):
        if not self.achievements_total:
            return 0
        return round((self.achievements_unlocked / self.achievements_total) * 100)
