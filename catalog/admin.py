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
    list_display = ('__str__', 'steam_app_id', 'steam_review_desc', 'steam_review_percent', 'release_date')
    search_fields = ('title', 'steam_app_id')
    filter_horizontal = ('categories',)
    inlines = [AchievementInline]
    actions = ['refresh_from_steam']

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change:
            try:
                sync_game(form.instance)
                self.message_user(request, f'Данные и достижения игры «{form.instance.title}» успешно загружены из Steam.')
            except SteamAPIError as e:
                self.message_user(request, f'Ошибка загрузки данных из Steam: {e}', level=messages.ERROR)

    @admin.action(description='Обновить из Steam (перезаписать поля и достижения)')
    def refresh_from_steam(self, request, queryset):
        success_count = 0
        errors = []
        for game in queryset:
            try:
                sync_game(game, overwrite=True)
                success_count += 1
            except SteamAPIError as e:
                errors.append(f'{game}: {e}')

        if success_count:
            self.message_user(request, f'Успешно обновлено игр: {success_count} из {queryset.count()}.')
        if errors:
            self.message_user(request, f'Ошибки при обновлении: {"; ".join(errors)}', level=messages.ERROR)

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


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('name', 'game', 'api_name', 'global_percent')
    search_fields = ('name', 'api_name', 'game__title')
    list_filter = ('game',)
    raw_id_fields = ('game',)
