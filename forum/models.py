from django.conf import settings
from django.db import models
from django.utils import timezone


class Topic(models.Model):
    game = models.ForeignKey(
        'catalog.Game',
        on_delete=models.CASCADE,
        related_name='topics',
        verbose_name='Игра',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='topics',
        verbose_name='Автор',
    )
    title = models.CharField('Тема', max_length=200)
    body = models.TextField('Описание')
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    last_activity = models.DateTimeField(
        'Последняя активность', default=timezone.now, db_index=True
    )

    class Meta:
        verbose_name = 'Тема'
        verbose_name_plural = 'Темы'
        ordering = ['-last_activity']

    def __str__(self):
        return self.title


class Post(models.Model):
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name='posts',
        verbose_name='Тема',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='forum_posts',
        verbose_name='Автор',
    )
    body = models.TextField('Сообщение')
    reply_to = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='replies',
        verbose_name='В ответ на',
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.author}: {self.body[:40]}'