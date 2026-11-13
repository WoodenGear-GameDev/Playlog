from django.db import models


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