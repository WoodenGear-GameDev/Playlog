from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from .confirmation import (
    activation_token,
    purge_expired_unconfirmed,
    send_confirmation_email,
)
from .forms import AvatarForm, RegisterForm, ResendConfirmationForm, UsernameForm
from .models import Profile


def register(request):
    if request.method == 'POST':
        purge_expired_unconfirmed()
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            send_confirmation_email(request, user)
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
                send_confirmation_email(request, user)
            return redirect('register_done')
    else:
        form = ResendConfirmationForm()
    return render(request, 'accounts/resend_confirmation.html', {'form': form})

@login_required
def profile(request):
    return render(request, 'accounts/profile.html', {'profile': request.user.profile})

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