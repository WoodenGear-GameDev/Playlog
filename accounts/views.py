from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth import views as auth_views, logout 
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from django.db import IntegrityError
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404

import secrets
import time
from urllib.parse import urlencode

from .steam_openid import build_login_url, verify_assertion

from .confirmation import (
    activation_token,
    purge_expired_unconfirmed,
    send_confirmation_email,
)
from .forms import AvatarForm, RegisterForm, ResendConfirmationForm, UsernameForm, DeleteAccountForm
from catalog.models import Game
from .models import LibraryGame, Profile
from .deletion import DeletionError, check_can_delete, content_summary, delete_user_account
from .self_delete import read_token, send_delete_email

DELETE_EMAIL_COOLDOWN = 60


def register(request):
    if request.method == 'POST':
        purge_expired_unconfirmed()
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            try:
                send_confirmation_email(request, user)
            except Exception:
                user.delete()
                form.add_error(
                    None,
                    'Не удалось отправить письмо. Проверьте адрес и попробуйте позже.',
                )
            else:
                return redirect('register_done')
    else:
        form = RegisterForm()
    return render(request, 'accounts/register.html', {'form': form})


def register_done(request):
    return render(request, 'accounts/register_done.html')


def resend_confirmation(request):
    if request.method == 'POST':
        form = ResendConfirmationForm(request.POST)
        if form.is_valid():
            user = get_user_model().objects.filter(
                email__iexact=form.cleaned_data['email'],
                is_active=False,
                last_login__isnull=True,
            ).first()
            if user:
                try:
                    send_confirmation_email(request, user)
                except Exception:
                    form.add_error(
                        None, 'Не удалось отправить письмо. Попробуйте позже.'
                    )
                    return render(
                        request, 'accounts/resend_confirmation.html', {'form': form}
                    )
            return redirect('register_done')
    else:
        form = ResendConfirmationForm()
    return render(request, 'accounts/resend_confirmation.html', {'form': form})

@login_required
def profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    page = Paginator(profile.library.all(), 48).get_page(request.GET.get('page'))
    return render(request, 'accounts/profile.html', {'profile': profile, 'page': page})

def activate(request, uidb64, token):
    User = get_user_model()
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and activation_token.check_token(user, token):
        user.is_active = True
        user.save(update_fields=['is_active'])
        return render(request, 'accounts/activation_success.html')
    return render(request, 'accounts/activation_failed.html')

@login_required
def profile_edit(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        username_form = UsernameForm(request.POST, instance=request.user)
        avatar_form = AvatarForm(request.POST, request.FILES, instance=profile)
        if username_form.is_valid() and avatar_form.is_valid():
            username_form.save()
            avatar_form.save()
            return redirect('profile')
    else:
        username_form = UsernameForm(instance=request.user)
        avatar_form = AvatarForm(instance=profile)
    return render(request, 'accounts/profile_edit.html', {
        'username_form': username_form,
        'avatar_form': avatar_form,
    })

@login_required
@require_POST
def steam_link_start(request):
    state = secrets.token_urlsafe(24)
    return_to = (
        request.build_absolute_uri(reverse('steam_callback'))
        + '?'
        + urlencode({'state': state})
    )
    request.session['steam_link_return_to'] = return_to
    realm = request.build_absolute_uri('/')
    return redirect(build_login_url(return_to, realm))


@login_required
def steam_link_callback(request):
    expected_return_to = request.session.pop('steam_link_return_to', None)
    steam_id = None
    if expected_return_to:
        steam_id = verify_assertion(request.GET, expected_return_to)

    if not steam_id:
        messages.error(
            request, 'Не удалось подтвердить Steam-аккаунт. Попробуйте ещё раз.'
        )
        return redirect('profile')

    profile, _ = Profile.objects.get_or_create(user=request.user)
    taken = Profile.objects.filter(steam_id=steam_id).exclude(pk=profile.pk)
    if taken.exists():
        messages.error(
            request, 'Этот Steam-аккаунт уже привязан к другому пользователю.'
        )
        return redirect('profile')

    old_steam_id = profile.steam_id
    profile.steam_id = steam_id
    try:
        profile.save(update_fields=['steam_id'])
    except IntegrityError:
        messages.error(
            request, 'Этот Steam-аккаунт уже привязан к другому пользователю.'
        )
        return redirect('profile')

    # Библиотека принадлежала прежнему аккаунту, при смене её нужно убрать
    if old_steam_id and old_steam_id != steam_id:
        profile.library.all().delete()

    messages.success(request, 'Steam-аккаунт подтверждён и привязан.')
    return redirect('profile')


@login_required
@require_POST
def steam_unlink(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.steam_id = ''
    profile.save(update_fields=['steam_id'])
    profile.steam_id = ''
    profile.save(update_fields=['steam_id'])
    profile.library.all().delete()
    messages.success(request, 'Steam-аккаунт отвязан.')
    return redirect('profile')

@login_required
def library_open(request, pk):
    # Только свои записи: чужие id дают 404
    entry = get_object_or_404(LibraryGame, pk=pk, profile__user=request.user)
    game = Game.objects.filter(steam_app_id=entry.steam_app_id).first()
    if game:
        return redirect('game_detail', pk=game.pk)

    messages.info(
        request, f'Игры «{entry.display_name}» пока нет в каталоге сайта.'
    )
    page_number = request.GET.get('page', '')
    suffix = f'?page={page_number}' if page_number.isdigit() else ''
    return redirect(f"{reverse('profile')}{suffix}#library")

class PasswordChange(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('profile')
    success_message = 'Пароль изменён.'

class PasswordResetRequest(SuccessMessageMixin, auth_views.PasswordResetView):
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/email/password_reset_email.txt'
    subject_template_name = 'accounts/email/password_reset_subject.txt'
    success_url = reverse_lazy('login')
    success_message = (
        'Если такой адрес зарегистрирован, мы отправили на него письмо '
        'со ссылкой для сброса пароля.'
    )


class PasswordResetConfirm(SuccessMessageMixin, auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('login')
    success_message = 'Пароль изменён. Войдите с новым паролем.'

@login_required
def account_delete(request):
    user = request.user
    if not user.email:
        messages.error(
            request,
            'У аккаунта не указана почта, поэтому подтвердить удаление письмом '
            'нельзя. Обратитесь к администратору.',
        )
        return redirect('profile')
    try:
        check_can_delete(user)
    except DeletionError as exc:
        messages.error(request, f'Удаление невозможно: {exc}')
        return redirect('profile')

    if request.method == 'POST':
        form = DeleteAccountForm(user, request.POST)
        if form.is_valid():
            last_sent = request.session.get('delete_email_sent_at', 0)
            if time.time() - last_sent < DELETE_EMAIL_COOLDOWN:
                form.add_error(None, 'Письмо уже отправлено. Повторить можно через минуту.')
            else:
                try:
                    send_delete_email(request, user, form.cleaned_data['mode'])
                except Exception:
                    form.add_error(None, 'Не удалось отправить письмо. Попробуйте позже.')
                else:
                    request.session['delete_email_sent_at'] = time.time()
                    messages.success(
                        request,
                        'Мы отправили письмо со ссылкой для подтверждения. '
                        'Ссылка действует 1 час.',
                    )
                    return redirect('profile')
    else:
        form = DeleteAccountForm(user)

    return render(request, 'accounts/account_delete.html', {
        'form': form,
        'summary': content_summary(user),
    })


@login_required
def account_delete_confirm(request, token):
    # Берём свежую запись из БД: нужен настоящий объект, а не обёртка request.user
    user = get_user_model().objects.get(pk=request.user.pk)
    mode = read_token(token, user)
    if mode is None:
        return render(request, 'accounts/account_delete_invalid.html')

    if request.method == 'POST':
        try:
            delete_user_account(user, purge_content=(mode == 'purge'))
        except DeletionError as exc:
            messages.error(request, f'Удаление невозможно: {exc}')
            return redirect('profile')
        logout(request)
        messages.success(request, 'Аккаунт удалён.')
        return redirect('home')

    return render(request, 'accounts/account_delete_confirm.html', {
        'mode': mode,
        'summary': content_summary(user),
    })