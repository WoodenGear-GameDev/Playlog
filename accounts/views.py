from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth import views as auth_views, logout 
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.http import HttpResponseForbidden, Http404

import secrets
import time
from urllib.parse import urlencode

from .steam_openid import build_login_url, verify_assertion
from .steam_service import sync_steam_account_library, sync_user_game_achievements

from .confirmation import (
    activation_token,
    purge_expired_unconfirmed,
    send_confirmation_email,
)
from .forms import AvatarForm, RegisterForm, ResendConfirmationForm, UsernameForm, DeleteAccountForm
from catalog.models import Achievement, Game, Rating, UserAchievement
from forum.models import GameInvite, Post, Topic
from .models import LibraryGame, Profile, SteamAccount, SteamLibrary
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
    steam_account = getattr(request.user, 'steam_account', None)
    library = getattr(steam_account, 'library', None) if steam_account else None
    
    # Автоматическая синхронизация при первом открытии профиля после привязки Steam
    if library and library.status == SteamLibrary.Status.NOT_SYNCED:
        sync_steam_account_library(library)
        library.refresh_from_db()

    library_games = []
    page = None
    remaining_cooldown = 0
    if library:
        games_qs = library.games.all()
        page = Paginator(games_qs, 48).get_page(request.GET.get('page'))
        library_games = list(page.object_list)
        app_ids = [g.steam_app_id for g in library_games]
        catalog_map = {
            g.steam_app_id: g for g in Game.objects.filter(steam_app_id__in=app_ids)
        }
        for g in library_games:
            g.catalog_game = catalog_map.get(g.steam_app_id)
            g.game = g.catalog_game

        if library.last_attempt_at and library.status != SteamLibrary.Status.NOT_SYNCED:
            elapsed = (timezone.now() - library.last_attempt_at).total_seconds()
            if elapsed < 120:
                remaining_cooldown = int(120 - elapsed)

    return render(request, 'accounts/profile.html', {
        'profile': profile,
        'steam_account': steam_account,
        'library': library,
        'page': page,
        'library_games': library_games,
        'remaining_cooldown': remaining_cooldown,
    })

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

    taken = SteamAccount.objects.filter(steam_id=steam_id).exclude(user=request.user)
    if taken.exists():
        messages.error(
            request, 'Этот аккаунт Steam уже привязан к другому профилю Playlog.'
        )
        return redirect('profile')

    # Если у пользователя уже был другой SteamID, удаление SteamAccount каскадно зачищает всё
    if hasattr(request.user, 'steam_account') and request.user.steam_account.steam_id != steam_id:
        request.user.steam_account.delete()

    steam_account, _ = SteamAccount.objects.get_or_create(
        user=request.user,
        defaults={'steam_id': steam_id},
    )
    if steam_account.steam_id != steam_id:
        steam_account.steam_id = steam_id
        steam_account.save(update_fields=['steam_id'])

    # Создаем пустую сущность библиотеки со статусом NOT_SYNCED (мгновенный редирект БЕЗ сетевых запросов)
    SteamLibrary.objects.get_or_create(
        steam_account=steam_account,
        defaults={'status': SteamLibrary.Status.NOT_SYNCED},
    )

    messages.success(request, 'Steam-аккаунт успешно привязан!')
    return redirect('profile')


@login_required
@require_POST
def steam_library_sync(request):
    steam_account = getattr(request.user, 'steam_account', None)
    if not steam_account:
        messages.error(request, 'Сначала привяжите Steam-аккаунт.')
        return redirect('profile')

    library, _ = SteamLibrary.objects.get_or_create(
        steam_account=steam_account,
        defaults={'status': SteamLibrary.Status.NOT_SYNCED},
    )
    force = request.POST.get('force') == '1'
    success, count, error_msg = sync_steam_account_library(library, force=force)
    if success:
        messages.success(
            request, f'Библиотека успешно синхронизирована! Всего игр: {count}.'
        )
    else:
        if error_msg:
            messages.warning(request, error_msg)
        else:
            messages.error(request, 'Не удалось синхронизировать библиотеку со Steam.')
    return redirect('profile')

steam_sync_library = steam_library_sync


@login_required
@require_POST
def steam_unlink(request):
    if hasattr(request.user, 'steam_account'):
        with transaction.atomic():
            request.user.steam_account.delete()
    messages.success(request, 'Steam-аккаунт отвязан.')
    return redirect('profile')

@login_required
def library_open(request, pk):
    # Только свои записи: чужие id дают 404
    entry = get_object_or_404(LibraryGame, pk=pk, library__steam_account__user=request.user)
    game = Game.objects.filter(steam_app_id=entry.steam_app_id).first()
    if game:
        return redirect('game_detail', pk=game.pk)

    url = reverse('steam_game_import', kwargs={'steam_app_id': entry.steam_app_id})
    params = urlencode({'title': entry.display_name, 'img': entry.header_image})
    return redirect(f"{url}?{params}")

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

@login_required
@require_POST
def profile_privacy(request):
    steam_account = getattr(request.user, 'steam_account', None)
    if steam_account:
        steam_account.show_steam = request.POST.get('show_steam') == '1'
        steam_account.save(update_fields=['show_steam'])
        if steam_account.show_steam:
            messages.success(request, 'Steam-профиль и библиотека теперь видны другим пользователям.')
        else:
            messages.success(request, 'Steam-профиль и библиотека скрыты от других пользователей.')
    else:
        messages.error(request, 'Сначала привяжите Steam-аккаунт.')
    return redirect('profile')

PUBLIC_LIBRARY_PER_PAGE = 24


def public_profile(request, pk):
    owner = get_object_or_404(get_user_model(), pk=pk, is_active=True)
    owner_profile = Profile.objects.filter(user=owner).first()
    steam_account = getattr(owner, 'steam_account', None)
    is_own = request.user.is_authenticated and request.user.pk == owner.pk

    stats = {
        'ratings': Rating.objects.filter(user=owner).count(),
        'reviews': Rating.objects.filter(user=owner).exclude(text='').count(),
        'topics': Topic.objects.filter(author=owner, is_deleted=False).count(),
        'posts': Post.objects.filter(author=owner, is_deleted=False).count(),
    }
    ratings = list(
        Rating.objects.filter(user=owner)
        .select_related('game')
        .order_by('-updated_at', '-pk')[:10]
    )
    topics = list(
        Topic.objects.filter(author=owner, is_deleted=False)
        .select_related('game')
        .order_by('-created_at', '-pk')[:10]
    )
    invites = list(
        GameInvite.objects.active().filter(author=owner).select_related('game')
    )

    steam_public = bool(
        steam_account and steam_account.show_steam
    )
    library = getattr(steam_account, 'library', None) if steam_account else None
    library_page = None
    library_entries = []
    if steam_public and library:
        library_page = Paginator(
            library.games.all(), PUBLIC_LIBRARY_PER_PAGE
        ).get_page(request.GET.get('page'))
        library_entries = list(library_page)
        app_ids = [g.steam_app_id for g in library_entries]
        catalog_map = {
            g.steam_app_id: g for g in Game.objects.filter(steam_app_id__in=app_ids)
        }
        for g in library_entries:
            g.catalog_game = catalog_map.get(g.steam_app_id)
            g.game = g.catalog_game

    return render(request, 'accounts/public_profile.html', {
        'owner': owner,
        'owner_profile': owner_profile,
        'steam_account': steam_account,
        'library': library,
        'is_own': is_own,
        'stats': stats,
        'ratings': ratings,
        'topics': topics,
        'invites': invites,
        'steam_public': steam_public,
        'library_page': library_page,
        'library_entries': library_entries,
    })


def user_game_achievements(request, user_pk, steam_app_id):
    owner = get_object_or_404(get_user_model(), pk=user_pk, is_active=True)
    owner_profile = Profile.objects.filter(user=owner).first()
    steam_account = getattr(owner, 'steam_account', None)
    if not steam_account:
        raise Http404('У пользователя не привязан Steam-аккаунт.')

    is_own = request.user.is_authenticated and request.user.pk == owner.pk
    if not is_own and not steam_account.show_steam:
        return HttpResponseForbidden('Пользователь скрыл библиотеку и достижения.')

    library = getattr(steam_account, 'library', None)
    library_entry = library.games.filter(steam_app_id=steam_app_id).first() if library else None
    game = Game.objects.filter(steam_app_id=steam_app_id).first()

    achievements = []
    unlocked_pks = set()
    if game:
        achievements = list(game.achievements.all())
        unlocked_pks = set(
            UserAchievement.objects.filter(steam_account=steam_account, achievement__game=game).values_list('achievement_id', flat=True)
        )

    for ach in achievements:
        ach.is_unlocked = ach.pk in unlocked_pks

    achievements.sort(key=lambda a: (not getattr(a, 'is_unlocked', False), getattr(a, 'global_percent', 0.0), a.pk))

    unlocked_total = len(unlocked_pks) if unlocked_pks else (library_entry.achievements_unlocked if library_entry else 0)
    ach_total = len(achievements) if achievements else (library_entry.achievements_total if library_entry else 0)
    locked_total = max(0, ach_total - unlocked_total)
    rare_total = sum(1 for a in achievements if a.is_rare or a.is_ultra_rare)
    percent = round((unlocked_total / ach_total) * 100) if ach_total else 0

    return render(request, 'accounts/_user_achievements_modal.html', {
        'owner': owner,
        'owner_profile': owner_profile,
        'steam_account': steam_account,
        'game': game,
        'library_entry': library_entry,
        'achievements': achievements,
        'unlocked_total': unlocked_total,
        'locked_total': locked_total,
        'rare_total': rare_total,
        'ach_total': ach_total,
        'percent': percent,
        'is_user_progress': True,
    })
