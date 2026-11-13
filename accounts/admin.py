from django.contrib import admin

from .models import LibraryGame, Profile


class LibraryGameInline(admin.TabularInline):
    model = LibraryGame
    extra = 1


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'steam_id')
    readonly_fields = ('steam_id',)
    inlines = [LibraryGameInline]