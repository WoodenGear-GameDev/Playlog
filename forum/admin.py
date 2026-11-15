from django.contrib import admin

from .models import GameInvite, Post, PostImage, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'game', 'author', 'created_at', 'last_activity')
    list_filter = ('game', 'is_deleted')
    search_fields = ('title', 'author__username')


class PostImageInline(admin.TabularInline):
    model = PostImage
    extra = 0
    readonly_fields = ('image', 'position')

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(GameInvite)
class GameInviteAdmin(admin.ModelAdmin):
    list_display = ('game', 'author', 'short_description', 'created_at', 'expires_at', 'closed_at', 'active')
    list_filter = ('game',)
    search_fields = ('description', 'author__username')
    raw_id_fields = ('game', 'author')

    @admin.display(description='Описание')
    def short_description(self, obj):
        return obj.description[:50]

    @admin.display(boolean=True, description='Активно')
    def active(self, obj):
        return obj.is_active


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'topic', 'game', 'author', 'created_at', 'is_deleted')
    list_filter = ('is_deleted',)
    search_fields = ('body', 'author__username')
    raw_id_fields = ('topic', 'game', 'reply_to')
    inlines = [PostImageInline]