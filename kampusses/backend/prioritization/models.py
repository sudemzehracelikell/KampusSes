from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

SCORE_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]


class Assessment(models.Model):
    """Kurul üyesinin bir bildirime verdiği aciliyet ve etki puanı."""

    report = models.ForeignKey("reports.Report", on_delete=models.CASCADE, related_name="assessments")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assessments")
    urgency = models.PositiveSmallIntegerField("aciliyet", validators=SCORE_VALIDATORS)
    impact = models.PositiveSmallIntegerField("etki", validators=SCORE_VALIDATORS)
    note = models.TextField("not", blank=True, max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "değerlendirme"
        verbose_name_plural = "değerlendirmeler"
        constraints = [
            models.UniqueConstraint(fields=["report", "reviewer"], name="one_assessment_per_reviewer"),
            models.CheckConstraint(condition=models.Q(urgency__gte=1, urgency__lte=5), name="urgency_1_5"),
            models.CheckConstraint(condition=models.Q(impact__gte=1, impact__lte=5), name="impact_1_5"),
        ]
