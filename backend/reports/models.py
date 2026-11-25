from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ReportStatus(models.TextChoices):
    NEW = "NEW", "Yeni"
    ASSIGNED = "ASSIGNED", "Atandı"
    IN_PROGRESS = "IN_PROGRESS", "İşlemde"
    RESOLVED = "RESOLVED", "Çözüldü"
    REJECTED = "REJECTED", "Reddedildi"

    @classmethod
    def closed(cls):
        return [cls.RESOLVED, cls.REJECTED]

    @classmethod
    def editable_by_owner(cls):
        """Bildirim sahibi, birim işleme başlayana kadar düzenleyip geri çekebilir."""
        return [cls.NEW, cls.ASSIGNED]


class Category(models.Model):
    name = models.CharField("ad", max_length=100, unique=True)
    description = models.TextField("açıklama", blank=True)
    default_unit = models.ForeignKey(
        "units.Unit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_categories",
        verbose_name="varsayılan birim",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "kategori"
        verbose_name_plural = "kategoriler"

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField("ad", max_length=50, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "etiket"
        verbose_name_plural = "etiketler"

    def __str__(self):
        return self.name


class Report(models.Model):
    """Kampüs sorun bildirimi."""

    title = models.CharField("başlık", max_length=150)
    description = models.TextField("açıklama")
    location = models.CharField("konum", max_length=150, help_text="Bina / kat / oda")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="reports", verbose_name="kategori")
    tags = models.ManyToManyField(Tag, blank=True, related_name="reports", verbose_name="etiketler")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports", verbose_name="bildiren"
    )
    assigned_unit = models.ForeignKey(
        "units.Unit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="atanan birim",
    )
    status = models.CharField("durum", max_length=20, choices=ReportStatus.choices, default=ReportStatus.NEW)
    is_removed = models.BooleanField("kaldırıldı", default=False, help_text="Admin tarafından uygunsuz bulunup gizlendi")
    # FR-06: Geri çekilen bildirim silinmez; listeden kalkar, durum geçmişi saklanır.
    is_withdrawn = models.BooleanField(
        "geri çekildi", default=False, help_text="Bildirim sahibi tarafından geri çekildi"
    )
    withdrawn_at = models.DateTimeField("geri çekilme zamanı", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "bildirim"
        verbose_name_plural = "bildirimler"
        indexes = [models.Index(fields=["status"]), models.Index(fields=["category", "status"])]

    def __str__(self):
        return f"#{self.pk} {self.title}"

    @property
    def is_closed(self):
        return self.status in ReportStatus.closed()


def validate_upload(file):
    ext = Path(file.name).suffix.lower().lstrip(".")
    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationError(
            "Desteklenmeyen dosya türü. İzin verilenler: " + ", ".join(settings.ALLOWED_UPLOAD_EXTENSIONS)
        )
    if file.size > settings.MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError(f"Dosya en fazla {settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB olabilir.")


class ReportMedia(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="media")
    file = models.FileField(upload_to="reports/%Y/%m/", validators=[validate_upload])
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ek"
        verbose_name_plural = "ekler"

    @property
    def is_image(self):
        return Path(self.file.name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


class StatusUpdate(models.Model):
    """Her durum değişikliğinin açıklamalı kaydı."""

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="status_updates")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    old_status = models.CharField(max_length=20, choices=ReportStatus.choices, blank=True)
    new_status = models.CharField(max_length=20, choices=ReportStatus.choices)
    unit = models.ForeignKey("units.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    note = models.TextField("açıklama")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "durum güncellemesi"
        verbose_name_plural = "durum güncellemeleri"


class EmailStatus(models.TextChoices):
    PENDING = "PENDING", "Gönderilecek"
    SENT = "SENT", "Gönderildi"
    FAILED = "FAILED", "Başarısız"


class EmailNotification(models.Model):
    """
    Durum değişikliği e-postası (FR-13, NFR-14). Her alıcı için ayrı kayıt tutulur;
    gönderilemeyen e-posta 1, 5 ve 15 dakika sonra yeniden denenir. Son deneme de
    başarısız olursa kayıt "Başarısız" olur ve Admin panelinde görünür.
    """

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="email_notifications")
    recipient = models.EmailField("alıcı")
    subject = models.CharField("konu", max_length=255)
    body = models.TextField("ileti")
    status = models.CharField("durum", max_length=10, choices=EmailStatus.choices, default=EmailStatus.PENDING)
    attempts = models.PositiveSmallIntegerField("deneme sayısı", default=0)
    next_attempt_at = models.DateTimeField("sonraki deneme", null=True, blank=True)
    last_error = models.TextField("son hata", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField("gönderilme zamanı", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "e-posta bildirimi"
        verbose_name_plural = "e-posta bildirimleri"
        indexes = [models.Index(fields=["status", "next_attempt_at"])]

    def __str__(self):
        return f"#{self.report_id} → {self.recipient} ({self.get_status_display()})"
