from django.contrib import admin, messages

from .models import Achievement, Category, Game, Rating, ReviewVote
from .steam_service import SteamAPIError
from .sync import sync_game


class AchievementInline(admin.TabularInline):
    model = Achievement
    extra = 0
    fields = ('name', 'api_name', 'global_percent', 'description')
    readonly_fields = ('api_name', 'global_percent')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'sort_order')
    list_editable = ('sort_order',)
    search_fields = ('name',)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'steam_app_id',
        'steam_review_desc',
        'steam_review_percent',
        'release_date',
        'schema_status',
    )
    search_fields = ('title', 'steam_app_id')
    filter_horizontal = ('categories',)
    readonly_fields = ('schema_status', 'schema_last_attempt_at', 'schema_error')
    inlines = [AchievementInline]
    actions = ['refresh_from_steam']

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change:
            try:
                sync_game(form.instance)
                self.message_user(
                    request,
                    f'Данные и достижения игры «{form.instance.title}» успешно загружены из Steam.',
                )
            except SteamAPIError as e:
                self.message_user(
                    request, f'Ошибка загрузки данных из Steam: {e}', level=messages.ERROR
                )

    @admin.action(description='Обновить данные и отзывы из Steam')
    def refresh_from_steam(self, request, queryset):
        success_count = 0
        error_count = 0
        for game in queryset:
            try:
                sync_game(game, overwrite=True)
                success_count += 1
            except SteamAPIError as e:
                error_count += 1
                self.message_user(
                    request,
                    f'Ошибка обновления для «{game.title}»: {e}',
                    level=messages.ERROR,
                )
        if success_count:
            self.message_user(
                request,
                f'Успешно обновлено игр из Steam: {success_count}.',
                level=messages.SUCCESS,
            )


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('user', 'game', 'value', 'created_at')
    search_fields = ('user__username', 'game__title')
    list_filter = ('value',)


@admin.register(ReviewVote)
class ReviewVoteAdmin(admin.ModelAdmin):
    list_display = ('user', 'rating', 'is_helpful', 'created_at')
    list_filter = ('is_helpful',)
