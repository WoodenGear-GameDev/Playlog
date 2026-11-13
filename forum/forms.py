from django import forms

from .models import Topic


class TopicForm(forms.ModelForm):
    body = forms.CharField(
        label='Описание',
        max_length=5000,
        widget=forms.Textarea(attrs={'rows': 8}),
    )

    class Meta:
        model = Topic
        fields = ('title', 'body')
        labels = {'title': 'Заголовок'}