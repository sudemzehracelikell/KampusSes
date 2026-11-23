from django.contrib import admin

from .models import Category, Report, ReportMedia, StatusUpdate, Tag


class ReportMediaInline(admin.TabularInline):
    model = ReportMedia
    extra = 0


class StatusUpdateInline(admin.TabularInline):
    model = StatusUpdate
    extra = 0
    readonly_fields = ("user", "old_status", "new_status", "unit", "note", "created_at")
    can_delete = False


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "category", "status", "assigned_unit", "created_by", "is_removed", "created_at")
    list_filter = ("status", "category", "assigned_unit", "is_removed")
    search_fields = ("title", "description", "location")
    inlines = [ReportMediaInline, StatusUpdateInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "default_unit")


admin.site.register(Tag)
