from django.contrib import admin, messages

from .models import Category, Game, Rating, ReviewVote
from .sync import describe_result, sync_game

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'sort_order')
    list_editable = ('sort_order',)
    search_fields = ('name',)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'steam_app_id', 'release_date', 'steam_synced_at')
    search_fields = ('title', 'steam_app_id')
    filter_horizontal = ('categories',)
    readonly_fields = ('steam_synced_at',)
    actions = ['refresh_from_steam']

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change:
            result = sync_game(form.instance)
            if result:
                self.message_user(request, describe_result(result))
            else:
                self.message_user(
                    request,
                    f'{result.error} Заполните поля вручную.',
                    level=messages.WARNING,
                )

    @admin.action(description='Обновить из Steam (заменить поля, которые удалось получить)')
    def refresh_from_steam(self, request, queryset):
        done = 0
        for game in queryset:
            result = sync_game(game, overwrite=True)
            if result:
                done += 1
            else:
                self.message_user(
                    request, f'{game}: {result.error}', level=messages.WARNING
                )
        self.message_user(request, f'Обновлено игр: {done} из {queryset.count()}.')

@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('game', 'author_name', 'value', 'has_review', 'updated_at')
    list_filter = ('value',)
    search_fields = ('game__title', 'user__username', 'text')
    raw_id_fields = ('user', 'game')

    @admin.display(boolean=True, description='Отзыв')
    def has_review(self, obj):
        return bool(obj.text)


@admin.register(ReviewVote)
class ReviewVoteAdmin(admin.ModelAdmin):
    list_display = ('rating', 'user', 'is_helpful', 'created_at')
    list_filter = ('is_helpful',)
    raw_id_fields = ('rating', 'user')