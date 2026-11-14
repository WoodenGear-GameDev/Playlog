from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import transaction


class DeletionError(Exception):
    """Пользователя нельзя удалить; причина в тексте исключения."""


def content_summary(user):
    from catalog.models import Rating
    from forum.models import Post, Topic

    return {
        'posts': Post.objects.filter(author=user, is_deleted=False).count(),
        'topics': Topic.objects.filter(author=user, is_deleted=False).count(),
        'ratings': Rating.objects.filter(user=user).count(),
    }


def _purge_content(user):
    from catalog.models import Rating
    from forum.models import Post, Topic

    for topic in Topic.objects.filter(author=user):
        if topic.posts.exclude(author=user).exists():
            # В теме отвечали другие: ветку сохраняем, содержимое убираем
            topic.title = 'Тема удалена'
            topic.body = ''
            topic.is_deleted = True
            topic.save(update_fields=['title', 'body', 'is_deleted'])
        else:
            topic.delete()

    Post.objects.filter(author=user).update(is_deleted=True, body='')
    Rating.objects.filter(user=user).delete()


def check_can_delete(user):
    """Бросает DeletionError, если учётную запись удалять нельзя."""
    if user.is_superuser:
        others = (
            get_user_model()
            .objects.filter(is_superuser=True, is_active=True)
            .exclude(pk=user.pk)
        )
        if not others.exists():
            raise DeletionError('нельзя удалить последнего активного суперпользователя.')

@transaction.atomic
def delete_user_account(user, purge_content=False):
    """Удаляет учётную запись.

    purge_content=False: сообщения, темы и оценки остаются, автор
    показывается как «Удалённый пользователь».
    purge_content=True: действия пользователя тоже убираются.
    """
    check_can_delete(user)

    if purge_content:
        _purge_content(user)

    profile = getattr(user, 'profile', None)
    avatar_name = profile.avatar.name if profile and profile.avatar else ''

    user.delete()

    if avatar_name:
        # Файл стираем, только когда транзакция успешно завершилась
        transaction.on_commit(lambda: default_storage.delete(avatar_name))