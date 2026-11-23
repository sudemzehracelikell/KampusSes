from django.conf import settings
from django.db import models


class Unit(models.Model):
    """Bildirimlerin atandığı kampüs birimi."""

    name = models.CharField("ad", max_length=100, unique=True)
    description = models.TextField("açıklama", blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="units", blank=True, verbose_name="personel")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "birim"
        verbose_name_plural = "birimler"

    def __str__(self):
        return self.name
