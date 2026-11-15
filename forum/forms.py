from django import forms
from django.db.models import Max

from .images import ImageRejected, compress_post_image
from .models import GameInvite, Post, PostImage, Topic

import re

MAX_IMAGES = 5
MAX_UPLOAD_SIZE = 8 * 1024 * 1024
MAX_TOTAL_SIZE = 20 * 1024 * 1024
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Поле для нескольких изображений (способ из документации Django)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'widget',
            MultipleFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp,image/gif'}),
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)]


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

class PostForm(forms.ModelForm):
    body = forms.CharField(
        label='Сообщение',
        required=False,
        max_length=5000,
        widget=forms.Textarea(attrs={'rows': 5}),
    )
    images = MultipleImageField(
        label=f'Изображения (до {MAX_IMAGES}, необязательно)',
        required=False,
    )
    # Какие уже прикреплённые картинки убрать (при редактировании). Поле скрытое:
    # чекбоксы рисуются вручную в post_edit.html
    remove_images = forms.ModelMultipleChoiceField(
        queryset=PostImage.objects.none(),
        required=False,
        widget=forms.MultipleHiddenInput,
    )

    class Meta:
        model = Post
        fields = ('body',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['remove_images'].queryset = self.instance.images.all()

    def clean_images(self):
        files = self.cleaned_data.get('images') or []
        if len(files) > MAX_IMAGES:
            raise forms.ValidationError(
                f'За один раз можно прикрепить не более {MAX_IMAGES} изображений.'
            )
        total = 0
        for file in files:
            if file.size > MAX_UPLOAD_SIZE:
                raise forms.ValidationError(
                    f'Файл «{file.name}» слишком большой. Максимум 8 МБ на файл.'
                )
            fmt = getattr(getattr(file, 'image', None), 'format', None)
            if fmt not in ALLOWED_FORMATS:
                raise forms.ValidationError(
                    f'Файл «{file.name}»: допустимы форматы JPEG, PNG, WebP и GIF.'
                )
            total += file.size
        if total > MAX_TOTAL_SIZE:
            raise forms.ValidationError('Суммарный размер файлов не должен превышать 20 МБ.')
        return files

    def clean(self):
        cleaned = super().clean()
        if self._errors:
            return cleaned

        new = cleaned.get('images') or []
        removed = list(cleaned.get('remove_images') or [])
        existing = self.instance.images.count() if self.instance.pk else 0
        remaining = existing - len(removed) + len(new)

        if remaining > MAX_IMAGES:
            self.add_error(
                'images',
                f'К сообщению можно прикрепить не более {MAX_IMAGES} изображений '
                f'(сейчас прикреплено: {existing}).',
            )
            return cleaned
        if not cleaned.get('body') and remaining == 0:
            raise forms.ValidationError('Напишите сообщение или прикрепите изображение.')

        # Тяжёлая работа (перекодирование) только после всех быстрых проверок
        try:
            cleaned['images'] = [compress_post_image(file) for file in new]
        except ImageRejected as exc:
            self.add_error('images', str(exc))
        return cleaned

    def has_real_changes(self):
        # Стандартный has_changed здесь всегда True из-за поля с файлами
        return (
            'body' in self.changed_data
            or bool(self.cleaned_data.get('images'))
            or bool(self.cleaned_data.get('remove_images'))
        )

    def save_images(self, post):
        """Удаляет отмеченные картинки и добавляет новые. Вызывать после сохранения post."""
        for image in list(self.cleaned_data.get('remove_images') or []):
            image.delete()  # файл с диска стирает обработчик из models.py

        last = post.images.aggregate(last=Max('position'))['last']
        position = 0 if last is None else last + 1
        for file in self.cleaned_data.get('images') or []:
            PostImage.objects.create(post=post, image=file, position=position)
            position += 1

URL_CHARS = r'[A-Za-z0-9._~:/?#@!$&()*+,;=%\-]+'
LINK_PATTERNS = [
    re.compile(r'steam://joinlobby/\d+/\d+/\d+'),
    re.compile(r'steam://connect/[A-Za-z0-9.\-]+(?::\d{1,5})?(?:/[A-Za-z0-9_\-]{1,64})?'),
    re.compile(r'https://s\.team/' + URL_CHARS),
    re.compile(r'https://steamcommunity\.com/' + URL_CHARS),
    re.compile(r'https://(?:www\.)?discord\.gg/[A-Za-z0-9\-]+'),
    re.compile(r'https://(?:www\.)?discord\.com/invite/[A-Za-z0-9\-]+'),
]

INVITE_HOURS = [
    (1, '1 час'), (2, '2 часа'), (3, '3 часа'), (4, '4 часа'),
    (5, '5 часов'), (6, '6 часов'), (7, '7 часов'), (8, '8 часов'),
]


class InviteForm(forms.ModelForm):
    description = forms.CharField(
        label='Описание',
        max_length=300,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Например: ищу двоих на кооператив, начинаем в 20:00',
        }),
    )
    link = forms.CharField(
        label='Ссылка (необязательно)',
        required=False,
        max_length=300,
        widget=forms.TextInput(attrs={'placeholder': 'steam://joinlobby/...'}),
    )
    join_code = forms.CharField(
        label='Код лобби или адрес сервера (необязательно)',
        required=False,
        max_length=100,
    )
    hours = forms.TypedChoiceField(
        label='Срок действия',
        choices=INVITE_HOURS,
        coerce=int,
        initial=2,
    )

    class Meta:
        model = GameInvite
        fields = ('description', 'link', 'join_code')

    def clean_link(self):
        link = self.cleaned_data['link'].strip()
        if link and not any(pattern.fullmatch(link) for pattern in LINK_PATTERNS):
            raise forms.ValidationError(
                'Такая ссылка не поддерживается. Допустимы steam://joinlobby/…, '
                'steam://connect/…, https://s.team/…, https://steamcommunity.com/… '
                'и приглашения Discord. Если ссылки нет, укажите код ниже.'
            )
        return link

    def clean_join_code(self):
        code = self.cleaned_data['join_code'].strip()
        if re.search(r'[\x00-\x1f\x7f<>]', code):
            raise forms.ValidationError('Код не должен содержать переносов строк и символов < >.')
        return code