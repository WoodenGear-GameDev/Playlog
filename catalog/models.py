from django.db import models


class Game(models.Model):
    title = models.CharField('Название', max_length=200)
    description = models.TextField('Описание', blank=True)
    release_date = models.DateField('Дата выхода', null=True, blank=True)

    class Meta:
        verbose_name = 'Игра'
        verbose_name_plural = 'Игры'
        ordering = ['title']

    def __str__(self):
        return self.title