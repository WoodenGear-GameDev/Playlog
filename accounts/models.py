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

    def __str__(self):
        return f'Профиль {self.user.username}'