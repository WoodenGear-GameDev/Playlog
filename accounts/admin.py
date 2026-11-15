from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse

from .deletion import DeletionError, content_summary, delete_user_account
from .models import LibraryGame, Profile, SteamAccount, SteamLibrary

User = get_user_model()


class LibraryGameInline(admin.TabularInline):
    model = LibraryGame
    extra = 0
    fields = ('steam_app_id', 'name', 'playtime_minutes', 'achievement_status', 'achievements_unlocked', 'achievements_total')
    readonly_fields = ('steam_app_id', 'name', 'playtime_minutes', 'achievement_status', 'achievements_unlocked', 'achievements_total')


@admin.register(SteamLibrary)
class SteamLibraryAdmin(admin.ModelAdmin):
    list_display = ('steam_account', 'status', 'total_games', 'last_attempt_at')
    readonly_fields = ('last_attempt_at',)
    inlines = [LibraryGameInline]


@admin.register(SteamAccount)
class SteamAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'steam_id', 'show_steam', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'avatar')


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    actions = ['delete_with_options']

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Удалить выбранных пользователей…')
    def delete_with_options(self, request, queryset):
        if not request.user.has_perm('auth.delete_user'):
            raise PermissionDenied

        targets = list(queryset.exclude(pk=request.user.pk))
        if len(targets) < queryset.count():
            self.message_user(
                request,
                'Текущий пользователь исключён из списка на удаление.',
                level=messages.WARNING,
            )
        if not targets:
            return

        summaries = [(u, content_summary(u)) for u in targets]
        return TemplateResponse(
            request,
            'admin/accounts/delete_users_confirm.html',
            {
                'users': targets,
                'summaries': summaries,
                'title': 'Подтверждение удаления пользователей',
            },
        )
