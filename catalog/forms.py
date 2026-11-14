from django import forms

from .models import Rating


class RatingForm(forms.ModelForm):
    text = forms.CharField(
        label='Отзыв (необязательно)',
        required=False,
        max_length=3000,
        widget=forms.Textarea(attrs={
            'rows': 5,
            'placeholder': 'Поделитесь впечатлениями об игре',
        }),
    )

    class Meta:
        model = Rating
        fields = ('value', 'text')
        labels = {'value': 'Ваша оценка'}
        error_messages = {
            'value': {'required': 'Выберите оценку от 1 до 10.'},
        }