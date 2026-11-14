from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac

SALT = 'accounts.self-delete'
MAX_AGE = 60 * 60  # ссылка действует 1 час
MODES = ('keep', 'purge')


def _fingerprint(user):
    # Отпечаток пароля: после смены пароля старая ссылка перестаёт работать
    return salted_hmac(SALT, user.password).hexdigest()[:20]


def make_token(user, mode):
    return signing.dumps(
        {'uid': user.pk, 'mode': mode, 'fp': _fingerprint(user)}, salt=SALT
    )


def read_token(token, user):
    """Возвращает режим ('keep' или 'purge') либо None, если ссылка недействительна."""
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:  # включает и просроченную подпись
        return None
    if data.get('uid') != user.pk or data.get('mode') not in MODES:
        return None
    if not constant_time_compare(str(data.get('fp', '')), _fingerprint(user)):
        return None
    return data['mode']


def send_delete_email(request, user, mode):
    link = request.build_absolute_uri(
        reverse('account_delete_confirm', args=[make_token(user, mode)])
    )
    message = render_to_string(
        'accounts/email/delete_confirm.txt',
        {'user': user, 'link': link, 'purge': mode == 'purge'},
    )
    send_mail('Подтверждение удаления аккаунта на Playlog', message, None, [user.email])