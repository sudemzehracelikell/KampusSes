"""
Bildirim iş kuralları. View'lar bu fonksiyonları çağırır; kurallar tek yerde
tutulduğu için hem test etmesi hem de değiştirmesi kolaydır.
"""
import logging

from django.db import transaction
from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import notifications
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
        is_withdrawn=False,
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
    _ensure_active(report, user)
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


def _ensure_active(report, user):
    """
    Kilit altında son kontrol. FR-06: geri çekilen kayıt salt okunurdur.
    FR-16: Admin'in gizlediği kayıtta yalnızca Admin işlem yapabilir.
    """
    if report.is_withdrawn:
        raise BusinessRuleError("Geri çekilmiş bir bildirim üzerinde işlem yapılamaz.")
    if report.is_removed and not (user and user.is_admin_role):
        raise BusinessRuleError("Gizlenmiş bir bildirim üzerinde işlem yapılamaz.")


@transaction.atomic
def update_report(report, user, *, tags=None, **fields):
    """
    Bildirimi düzenler (FR-06). Kayıt kilit altında yeniden okunur ve yalnızca değişen
    alanlar yazılır; böylece aynı anda yapılan geri çekme veya durum değişikliği ezilmez.
    """
    report = Report.objects.select_for_update().get(pk=report.pk)
    _ensure_active(report, user)
    if not user.is_admin_role and report.status not in ReportStatus.editable_by_owner():
        raise BusinessRuleError("Birim işleme başladıktan sonra bildirim değiştirilemez.")
    for field, value in fields.items():
        setattr(report, field, value)
    if fields or tags is not None:  # Yalnızca etiket değişse de güncellenme zamanı yazılır.
        report.save(update_fields=[*fields, "updated_at"])
    if tags is not None:
        report.tags.set(tags)
    return report


@transaction.atomic
def withdraw_report(report, user):
    """
    Bildirimi sahibi adına geri çeker (FR-06). Kayıt silinmez: listeden kalkar,
    durum geçmişi saklanır ve geri çekme de geçmişe yazılır.
    """
    report = Report.objects.select_for_update().get(pk=report.pk)
    _ensure_active(report, user)
    # Yetki view'da kontrol edildi; durum o arada değişmiş olabileceği için kilit altında tekrar bakılır.
    if report.status not in ReportStatus.editable_by_owner():
        raise BusinessRuleError("Birim işleme başladıktan sonra bildirim geri çekilemez.")
    report.is_withdrawn = True
    report.withdrawn_at = timezone.now()
    report.save(update_fields=["is_withdrawn", "withdrawn_at", "updated_at"])
    StatusUpdate.objects.create(
        report=report,
        user=user,
        old_status=report.status,
        new_status=report.status,
        unit=report.assigned_unit,
        note="Bildirim, sahibi tarafından geri çekildi.",
    )
    return report


@transaction.atomic
def reassign(report, user, unit, note):
    """Bildirimi başka bir birime aktarır (UC-05, alternatif akış 2a)."""
    report = Report.objects.select_for_update().get(pk=report.pk)
    _ensure_active(report, user)
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
    """
    E-postalar durum değişikliği veritabanına yazıldıktan sonra gönderilir (on_commit);
    gönderim hatası değişikliği geri almaz. Ayrıntılar: notifications.py (FR-13, NFR-14).
    """
    try:
        notifications.notify_status_change(report, new_status, note)
    except Exception:  # Kayıt oluşturulamasa bile durum değişikliği geri alınmaz.
        logger.exception("Durum bildirimi e-postaları hazırlanamadı (rapor #%s)", report.pk)
