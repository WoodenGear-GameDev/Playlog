from django.contrib import admin, messages

from .models import Category, Game
from .sync import sync_game


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'sort_order')
    list_editable = ('sort_order',)
    search_fields = ('name',)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'steam_app_id', 'release_date')
    search_fields = ('title', 'steam_app_id')
    filter_horizontal = ('categories',)
    actions = ['refresh_from_steam']

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change:
            if sync_game(form.instance):
                self.message_user(request, 'Данные подтянуты из Steam.')
            else:
                self.message_user(
                    request,
                    'Не удалось получить данные из Steam. Заполните поля вручную.',
                    level=messages.WARNING,
                )

    @admin.action(description='Обновить из Steam (перезаписать поля)')
    def refresh_from_steam(self, request, queryset):
        updated = sum(sync_game(game, overwrite=True) for game in queryset)
        self.message_user(request, f'Обновлено игр: {updated} из {queryset.count()}')