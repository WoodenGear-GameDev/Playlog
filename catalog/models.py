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
    steam_app_id = models.PositiveIntegerField('Steam AppID', unique=True)
    title = models.CharField('Название', max_length=200, blank=True)
    description = models.TextField('Описание', blank=True)
    release_date = models.DateField('Дата выхода', null=True, blank=True)
    header_image = models.URLField('Обложка (URL)', max_length=500, blank=True)
    categories = models.ManyToManyField(
        Category,
        related_name='games',
        blank=True,
        verbose_name='Категории',
    )

    class Meta:
        verbose_name = 'Игра'
        verbose_name_plural = 'Игры'
        ordering = ['title']

    def __str__(self):
        return self.title or f'Steam app {self.steam_app_id}'


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