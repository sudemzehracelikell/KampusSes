from django.conf import settings
from django.db import models


class Support(models.Model):
    """'Ben de yaşıyorum' desteği."""

    report = models.ForeignKey("reports.Report", on_delete=models.CASCADE, related_name="supports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="supports")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "destek"
        verbose_name_plural = "destekler"
        # Bir kullanıcı bir bildirime bir kez destek verebilir; kural veritabanı
        # düzeyinde korunur, eşzamanlı isteklerde de çift kayıt oluşmaz (NFR-06, B7).
        constraints = [models.UniqueConstraint(fields=["report", "user"], name="unique_support_per_user")]


class Comment(models.Model):
    report = models.ForeignKey("reports.Report", on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField("yorum", max_length=1000)
    is_official = models.BooleanField("resmi yanıt", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "yorum"
        verbose_name_plural = "yorumlar"

    def __str__(self):
        return f"{self.user} - {self.text[:30]}"
