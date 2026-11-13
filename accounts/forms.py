from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


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