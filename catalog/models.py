from django.db import models
from django.conf import settings

from accounts.constants import DELETED_USER_NAME


class Category(models.Model):
    name = models.CharField('Название', max_length=100, unique=True)
    sort_order = models.PositiveIntegerField('Порядок в каталоге', default=0)

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Game(models.Model):
    class SchemaStatus(models.TextChoices):
        NOT_FETCHED = 'not_fetched', 'Схема не загружена'
        FETCHING = 'fetching', 'Загрузка схемы'
        READY = 'ready', 'Схема загружена'
        NO_ACHIEVEMENTS = 'no_achievements', 'В игре нет достижений в Steam'
        ERROR = 'error', 'Ошибка загрузки схемы'

    steam_app_id = models.PositiveIntegerField('Steam AppID', unique=True, db_index=True)
    title = models.CharField('Название', max_length=255)
    description = models.TextField('Описание', default='', blank=True)
    release_date = models.DateField('Дата выхода', null=True, blank=True)
    header_image = models.URLField('Обложка (Store API)', max_length=500, default='', blank=True)
    categories = models.ManyToManyField(
        Category,
        related_name='games',
        blank=True,
        verbose_name='Категории',
    )
    steam_review_desc = models.CharField('Оценка отзывов', max_length=100, default='', blank=True)
    steam_review_percent = models.PositiveSmallIntegerField('Положительных отзывов (%)', default=0)
    steam_review_total = models.PositiveIntegerField('Всего отзывов', default=0)

    schema_status = models.CharField(
        'Статус схемы достижений',
        max_length=20,
        choices=SchemaStatus.choices,
        default=SchemaStatus.NOT_FETCHED,
    )
    schema_last_attempt_at = models.DateTimeField('Последняя попытка загрузки схемы', auto_now_add=True)
    schema_error = models.CharField('Ошибка схемы', max_length=500, default='', blank=True)

    class Meta:
        verbose_name = 'Игра'
        verbose_name_plural = 'Игры'
        ordering = ['title']

    def __str__(self):
        return self.title or f'Steam app {self.steam_app_id}'

    @property
    def steam_store_url(self):
        return f'https://store.steampowered.com/app/{self.steam_app_id}/' if self.steam_app_id else ''

    @property
    def steam_community_reviews_url(self):
        return f'https://steamcommunity.com/app/{self.steam_app_id}/reviews/' if self.steam_app_id else ''


RATING_CHOICES = [(i, str(i)) for i in range(1, 11)]


class Rating(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ratings',
        verbose_name='Пользователь',
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name='ratings',
        verbose_name='Игра',
    )
    value = models.PositiveSmallIntegerField('Оценка', choices=RATING_CHOICES)
    text = models.TextField('Отзыв', blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Изменена', auto_now=True)

    class Meta:
        verbose_name = 'Оценка'
        verbose_name_plural = 'Оценки'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'game'], name='unique_rating_per_user_game'
            ),
        ]

    @property
    def author_name(self):
        return self.user.username if self.user_id else DELETED_USER_NAME

    def __str__(self):
        return f'{self.author_name} → {self.game}: {self.value}'


class ReviewVote(models.Model):
    rating = models.ForeignKey(
        Rating,
        on_delete=models.CASCADE,
        related_name='votes',
        verbose_name='Отзыв',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='review_votes',
        verbose_name='Пользователь',
    )
    is_helpful = models.BooleanField('Полезно')
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Голос за отзыв'
        verbose_name_plural = 'Голоса за отзывы'
        constraints = [
            models.UniqueConstraint(
                fields=['rating', 'user'], name='unique_vote_per_review_user'
            ),
        ]

    def __str__(self):
        return f'{self.user} → {self.rating_id}: {"полезно" if self.is_helpful else "бесполезно"}'


class Achievement(models.Model):
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name='achievements',
        verbose_name='Игра',
    )
    api_name = models.CharField('Технический ID в Steam', max_length=128)
    name = models.CharField('Название', max_length=255)
    description = models.TextField('Описание', default='', blank=True)
    icon_url = models.URLField('Цветная иконка', max_length=500, default='', blank=True)
    icon_gray_url = models.URLField('Серая иконка', max_length=500, default='', blank=True)
    global_percent = models.FloatField('Редкость (%)', default=0.0)

    class Meta:
        verbose_name = 'Достижение'
        verbose_name_plural = 'Достижения'
        unique_together = ('game', 'api_name')
        ordering = ['global_percent', 'pk']

    def __str__(self):
        return f'{self.game.title} — {self.name}'

    @property
    def is_rare(self):
        return 0.0 < self.global_percent <= 10.0

    @property
    def is_ultra_rare(self):
        return 0.0 < self.global_percent <= 3.0


class UserAchievement(models.Model):
    """Выбитое пользователем достижение."""

    steam_account = models.ForeignKey(
        'accounts.SteamAccount',
        on_delete=models.CASCADE,
        related_name='unlocked_achievements',
        verbose_name='Аккаунт Steam',
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name='unlocked_by_users',
        verbose_name='Достижение',
    )
    unlocked_at = models.DateTimeField('Время получения в Steam', null=True, blank=True)

    class Meta:
        verbose_name = 'Выбитое достижение'
        verbose_name_plural = 'Выбитые достижения'
        unique_together = ('steam_account', 'achievement')

    def __str__(self):
        return f'{self.steam_account} → {self.achievement}'
