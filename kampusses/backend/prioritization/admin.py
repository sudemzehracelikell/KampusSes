from django.contrib import admin

from .models import Assessment


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("report", "reviewer", "urgency", "impact", "updated_at")
