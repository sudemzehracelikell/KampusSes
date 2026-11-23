from django.contrib import admin

from .models import Comment, Support


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("report", "user", "is_official", "created_at")
    list_filter = ("is_official",)


@admin.register(Support)
class SupportAdmin(admin.ModelAdmin):
    list_display = ("report", "user", "created_at")
