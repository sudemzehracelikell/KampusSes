from django.contrib import admin

from .models import Category, EmailNotification, Report, ReportMedia, StatusUpdate, Tag


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
    list_display = (
        "id", "title", "category", "status", "assigned_unit", "created_by", "is_removed", "is_withdrawn", "created_at",
    )
    list_filter = ("status", "category", "assigned_unit", "is_removed", "is_withdrawn")
    search_fields = ("title", "description", "location")
    inlines = [ReportMediaInline, StatusUpdateInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "default_unit")


admin.site.register(Tag)


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    """NFR-14: Son denemede de gönderilemeyen e-postalar burada yetkiliye görünür."""

    list_display = (
        "report", "recipient", "status", "attempts", "short_error", "next_attempt_at", "sent_at", "created_at",
    )
    list_filter = ("status",)
    search_fields = ("recipient", "subject")
    readonly_fields = [field.name for field in EmailNotification._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.display(description="son hata")
    def short_error(self, obj):
        return obj.last_error[:80]
