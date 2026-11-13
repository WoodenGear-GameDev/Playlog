from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile

from .models import Profile


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label='Электронная почта')

    class Meta(UserCreationForm.Meta):
        fields = ('username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'Эта почта уже используется. Если вы не получили письмо '
                'подтверждения, запросите его повторно.'
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = False
        if commit:
            user.save()
        return user


class ResendConfirmationForm(forms.Form):
    email = forms.EmailField(label='Электронная почта')

class UsernameForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('username',)

    def clean_username(self):
        username = self.cleaned_data['username']
        taken = get_user_model().objects.filter(username__iexact=username)
        taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError('Это имя пользователя уже занято.')
        return username


class AvatarForm(forms.ModelForm):
    MAX_SIZE = 2 * 1024 * 1024  # 2 МБ

    class Meta:
        model = Profile
        fields = ('avatar',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Запоминаем старый файл, чтобы удалить его после замены
        self._old_avatar = self.instance.avatar.name if self.instance.pk else ''

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if isinstance(avatar, UploadedFile) and avatar.size > self.MAX_SIZE:
            raise forms.ValidationError('Файл слишком большой. Максимум 2 МБ.')
        return avatar

    def save(self, commit=True):
        profile = super().save(commit=commit)
        new_name = profile.avatar.name or ''
        if commit and self._old_avatar and self._old_avatar != new_name:
            default_storage.delete(self._old_avatar)
        return profile