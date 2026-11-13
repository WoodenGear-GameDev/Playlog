from django.contrib import admin

from .models import Post, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'game', 'author', 'created_at', 'last_activity')
    list_filter = ('game',)
    search_fields = ('title', 'author__username')


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('topic', 'author', 'created_at')
    search_fields = ('body', 'author__username')
    raw_id_fields = ('topic', 'reply_to')