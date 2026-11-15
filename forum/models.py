from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.core.files.storage import default_storage
from django.db.models.signals import post_delete
from django.dispatch import receiver

from accounts.constants import DELETED_USER_NAME

import uuid

def post_image_path(instance, filename):
    # Имя файла всегда случайное, а расширение наше: исходное имя не сохраняется
    return f'forum/{uuid.uuid4().hex}.webp'


def _delete_file_on_commit(name):
    if name:
        transaction.on_commit(lambda: default_storage.delete(name))

class Topic(models.Model):
    game = models.ForeignKey(
        'catalog.Game',
        on_delete=models.CASCADE,
        related_name='topics',
        verbose_name='Игра',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='topics',
        verbose_name='Автор',
    )
    title = models.CharField('Тема', max_length=200)
    body = models.TextField('Описание')
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    last_activity = models.DateTimeField(
        'Последняя активность', default=timezone.now, db_index=True
    )

    is_deleted = models.BooleanField('Удалена', default=False)

    class Meta:
        verbose_name = 'Тема'
        verbose_name_plural = 'Темы'
        ordering = ['-last_activity']

    def __str__(self):
        return self.title

    @property
    def author_name(self):
        return self.author.username if self.author_id else DELETED_USER_NAME


class Post(models.Model):
    topic = models.ForeignKey(
        Topic,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='posts',
        verbose_name='Тема',
    )
    game = models.ForeignKey(
        'catalog.Game',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='chat_posts',
        verbose_name='Игра (общий чат)',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='forum_posts',
        verbose_name='Автор',
    )
    body = models.TextField('Сообщение', blank=True)
    reply_to = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='replies',
        verbose_name='В ответ на',
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    edited_at = models.DateTimeField('Изменено', null=True, blank=True)
    is_deleted = models.BooleanField('Удалено', default=False)

    class Meta:
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'
        ordering = ['created_at', 'id']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(topic__isnull=False, game__isnull=True)
                    | models.Q(topic__isnull=True, game__isnull=False)
                ),
                name='post_in_topic_or_game_chat',
            ),
        ]

    def __str__(self):
        return f'{self.author_name}: {self.body[:40] or "[без текста]"}'

    @property
    def author_name(self):
        return self.author.username if self.author_id else DELETED_USER_NAME

class PostImage(models.Model):
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Сообщение',
    )
    image = models.ImageField('Изображение', upload_to=post_image_path)
    position = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Изображение сообщения'
        verbose_name_plural = 'Изображения сообщений'
        ordering = ['position', 'pk']

    def __str__(self):
        return f'Изображение {self.pk} к сообщению {self.post_id}'


@receiver(post_delete, sender=PostImage)
def delete_image_file(sender, instance, **kwargs):
    # Срабатывает при любом удалении записи, в том числе каскадном
    # (удалили сообщение, тему или пользователя)
    if instance.image:
        _delete_file_on_commit(instance.image.name)