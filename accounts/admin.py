from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse

from .deletion import DeletionError, content_summary, delete_user_account
from .models import LibraryGame, Profile

User = get_user_model()


class LibraryGameInline(admin.TabularInline):
    model = LibraryGame
    extra = 1


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'steam_id')
    readonly_fields = ('steam_id',)
    inlines = [LibraryGameInline]


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    actions = ['delete_with_options']

    def has_delete_permission(self, request, obj=None):
        # Обычное удаление отключено: оно стирало бы чужие ответы
        return False

    @admin.action(description='Удалить выбранных пользователей…')
    def delete_with_options(self, request, queryset):
        if not request.user.has_perm('auth.delete_user'):
            raise PermissionDenied

        targets = list(queryset.exclude(pk=request.user.pk))
        if len(targets) < queryset.count():
            self.message_user(
                request, 'Себя удалить нельзя: ваша запись пропущена.',
                level=messages.WARNING,
            )
        if not targets:
            return None

        if request.POST.get('confirm') == '1':
            purge = request.POST.get('mode') == 'purge'
            done = 0
            for user in targets:
                try:
                    if user.is_superuser and not request.user.is_superuser:
                        raise DeletionError(
                            'суперпользователя может удалить только суперпользователь.'
                        )
                    delete_user_account(user, purge_content=purge)
                    done += 1
                except DeletionError as exc:
                    self.message_user(
                        request, f'{user.username}: {exc}', level=messages.ERROR
                    )
            if done:
                self.message_user(
                    request, f'Удалено пользователей: {done}.', level=messages.SUCCESS
                )
            return None

        context = {
            **self.admin_site.each_context(request),
            'title': 'Удаление пользователей',
            'opts': self.model._meta,
            'items': [{'user': u, **content_summary(u)} for u in targets],
        }
        return TemplateResponse(
            request, 'admin/accounts/delete_users_confirm.html', context
        )