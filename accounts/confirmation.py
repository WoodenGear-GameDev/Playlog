from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


class ActivationTokenGenerator(PasswordResetTokenGenerator):
    # Свой «соль»: токен подтверждения нельзя использовать как токен сброса пароля
    key_salt = 'accounts.ActivationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        # В подпись входит is_active и last_login: после активации ссылка
        # перестаёт работать (одноразовая), а заблокированный админом пользователь
        # не сможет вернуть доступ старой ссылкой
        return f'{user.pk}{user.is_active}{user.last_login}{timestamp}'


activation_token = ActivationTokenGenerator()


def send_confirmation_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = activation_token.make_token(user)
    link = request.build_absolute_uri(reverse('activate', args=[uid, token]))
    message = render_to_string(
        'accounts/email/confirm.txt', {'user': user, 'link': link}
    )
    send_mail('Подтверждение почты на Playlog', message, None, [user.email])


def purge_expired_unconfirmed():
    """Удаляет так и не подтверждённые аккаунты, у которых истёк срок ссылки."""
    limit = timezone.now() - timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)
    get_user_model().objects.filter(
        is_active=False,
        last_login__isnull=True,
        date_joined__lt=limit,
    ).delete()