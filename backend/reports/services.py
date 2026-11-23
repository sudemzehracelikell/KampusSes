"""
Bildirim iş kuralları. View'lar bu fonksiyonları çağırır; kurallar tek yerde
tutulduğu için hem test etmesi hem de değiştirmesi kolaydır.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Value
from django.db.models.functions import Coalesce

from .models import Report, ReportStatus, StatusUpdate

logger = logging.getLogger(__name__)

# Geçerli durum geçişleri (FR-12). Kapalı durumlardan çıkış yoktur.
ALLOWED_TRANSITIONS = {
    ReportStatus.NEW: {ReportStatus.ASSIGNED, ReportStatus.REJECTED},
    ReportStatus.ASSIGNED: {ReportStatus.IN_PROGRESS, ReportStatus.REJECTED},
    ReportStatus.IN_PROGRESS: {ReportStatus.RESOLVED, ReportStatus.REJECTED},
    ReportStatus.RESOLVED: set(),
    ReportStatus.REJECTED: set(),
}

# Öncelik skoru (FR-15): kurul puan ortalaması (1–5) × 10 + destek sayısı.
BOARD_SCORE_WEIGHT = 10


class BusinessRuleError(Exception):
    """Bir iş kuralı ihlal edildiğinde fırlatılır; API 400 olarak döner."""


def can_transition(old, new):
    return new in ALLOWED_TRANSITIONS.get(old, set())


def user_manages_report(user, report):
    """Kullanıcı, bildirimin atandığı birimin personeli mi (veya Admin mi)?"""
    if not user.is_authenticated:
        return False
    if user.is_admin_role:
        return True
    return bool(
        user.is_unit_manager
        and report.assigned_unit_id
        and report.assigned_unit.members.filter(pk=user.pk).exists()
    )


def with_priority(queryset):
    """Listeye destek sayısı, kurul ortalaması ve öncelik skoru ekler."""
    board_avg = Avg(
        ExpressionWrapper((F("assessments__urgency") + F("assessments__impact")) / 2.0, output_field=FloatField())
    )
    return queryset.annotate(
        support_count=Count("supports", distinct=True),
        comment_count=Count("comments", distinct=True),
        board_score=Coalesce(board_avg, Value(0.0), output_field=FloatField()),
    ).annotate(
        priority_score=ExpressionWrapper(
            F("board_score") * BOARD_SCORE_WEIGHT + F("support_count"), output_field=FloatField()
        )
    )


def find_similar(category_id, location, exclude_id=None, limit=5):
    """Aynı kategori ve benzer konumdaki açık bildirimler."""
    if not category_id or not location:
        return Report.objects.none()
    qs = Report.objects.filter(
        category_id=category_id,
        location__icontains=location.strip()[:50],
        is_removed=False,
    ).exclude(status__in=ReportStatus.closed())
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return with_priority(qs).order_by("-support_count")[:limit]


@transaction.atomic
def create_report(user, *, tags=None, **fields):
    """Bildirimi kaydeder ve kategorinin varsayılan birimine otomatik atar (FR-11)."""
    report = Report.objects.create(created_by=user, **fields)
    if tags:
        report.tags.set(tags)
    StatusUpdate.objects.create(
        report=report, user=user, old_status="", new_status=ReportStatus.NEW, note="Bildirim oluşturuldu."
    )
    unit = report.category.default_unit
    if unit:
        report.assigned_unit = unit
        report.status = ReportStatus.ASSIGNED
        report.save(update_fields=["assigned_unit", "status", "updated_at"])
        StatusUpdate.objects.create(
            report=report,
            user=None,
            old_status=ReportStatus.NEW,
            new_status=ReportStatus.ASSIGNED,
            unit=unit,
            note=f"Kategoriye göre otomatik olarak {unit.name} birimine atandı.",
        )
    return report


@transaction.atomic
def change_status(report, user, new_status, note):
    """Durum geçişini doğrular, kaydeder ve ilgilileri bilgilendirir (FR-12, FR-13)."""
    report = Report.objects.select_for_update().get(pk=report.pk)
    if not note or not note.strip():
        raise BusinessRuleError("Durum değişikliği için açıklama yazılmalıdır.")
    if not can_transition(report.status, new_status):
        raise BusinessRuleError(
            f"'{ReportStatus(report.status).label}' durumundan "
            f"'{ReportStatus(new_status).label}' durumuna geçilemez."
        )
    if new_status == ReportStatus.ASSIGNED and not report.assigned_unit_id:
        raise BusinessRuleError("Bildirimi 'Atandı' yapmak için önce bir birime atayın.")

    old = report.status
    report.status = new_status
    report.save(update_fields=["status", "updated_at"])
    StatusUpdate.objects.create(
        report=report, user=user, old_status=old, new_status=new_status, unit=report.assigned_unit, note=note.strip()
    )
    transaction.on_commit(lambda: notify_status_change(report, new_status, note.strip()))
    return report


@transaction.atomic
def reassign(report, user, unit, note):
    """Bildirimi başka bir birime aktarır (UC-05, alternatif akış 2a)."""
    report = Report.objects.select_for_update().get(pk=report.pk)
    if report.is_closed:
        raise BusinessRuleError("Kapanmış bir bildirim yeniden atanamaz.")
    if report.assigned_unit_id == unit.pk:
        raise BusinessRuleError("Bildirim zaten bu birime atanmış.")
    old = report.status
    report.assigned_unit = unit
    report.status = ReportStatus.ASSIGNED
    report.save(update_fields=["assigned_unit", "status", "updated_at"])
    StatusUpdate.objects.create(
        report=report,
        user=user,
        old_status=old,
        new_status=ReportStatus.ASSIGNED,
        unit=unit,
        note=(note or "").strip() or f"{unit.name} birimine yeniden atandı.",
    )
    return report


def notify_status_change(report, new_status, note):
    recipients = {report.created_by.email}
    recipients.update(report.supports.select_related("user").values_list("user__email", flat=True))
    recipients.discard("")
    if not recipients:
        return
    try:
        send_mail(
            subject=f"[KampüsSes] #{report.pk} bildiriminin durumu: {ReportStatus(new_status).label}",
            message=f"'{report.title}' bildiriminin durumu '{ReportStatus(new_status).label}' oldu.\n\nAçıklama: {note}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=sorted(recipients),
            fail_silently=False,
        )
    except Exception:  # E-posta gönderilemese bile durum değişikliği geri alınmaz.
        logger.exception("Durum bildirimi e-postası gönderilemedi (rapor #%s)", report.pk)
