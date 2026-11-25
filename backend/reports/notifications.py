"""
Durum değişikliği e-postaları (FR-13) ve hata yönetimi (NFR-14).

- Her alıcıya ayrı e-posta gider; alıcılar birbirinin adresini görmez ve aynı adrese
  tek e-posta gider (adresler küçük harfe çevrilip tekilleştirilir).
- E-posta gönderilemezse durum değişikliği geri alınmaz (e-postalar, değişiklik
  veritabanına yazıldıktan sonra gönderilir). Hata kaydedilir.
- Gönderilemeyen e-posta 1, 5 ve 15 dakika sonra yeniden denenir. Son deneme de
  başarısız olursa kayıt "Başarısız" olur ve Admin panelinde görünür.
- Yeniden denemeleri `python manage.py retry_emails` komutu yapar (bkz. README).
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F
from django.utils import timezone

from .models import EmailNotification, EmailStatus, ReportStatus

logger = logging.getLogger(__name__)

# İlk denemeden sonraki bekleme süreleri (NFR-14). İlk deneme + 3 yeniden deneme = en fazla 4 deneme.
RETRY_DELAYS = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15)]
# Gönderim sırasında süreç çökerse sahiplenilen kayıt bu süre sonra yeniden denenir.
CLAIM_TIMEOUT = timedelta(minutes=5)


def status_change_recipients(report):
    """Bildirimi açan kişi ve destek verenler; her adres bir kez."""
    emails = [report.created_by.email, *report.supports.values_list("user__email", flat=True)]
    return sorted({email.strip().lower() for email in emails if email and email.strip()})


def notify_status_change(report, new_status, note):
    """Her alıcı için bir e-posta kaydı oluşturur ve hemen göndermeyi dener."""
    label = ReportStatus(new_status).label
    subject = f"[KampüsSes] #{report.pk} bildiriminin durumu: {label}"
    body = f"'{report.title}' bildiriminin durumu '{label}' oldu.\n\nAçıklama: {note}"
    now = timezone.now()
    # next_attempt_at baştan dolu: gönderim yarıda kesilirse (sunucu kapanması vb.) kalan kayıtlar
    # retry_emails tarafından bulunur; hiçbir e-posta sessizce kaybolmaz (NFR-14).
    notifications = [
        EmailNotification.objects.create(
            report=report, recipient=email, subject=subject, body=body, next_attempt_at=now
        )
        for email in status_change_recipients(report)
    ]
    for notification in notifications:
        deliver(notification)
    return notifications


def _claim(notification, now):
    """
    Kaydı gönderim için sahiplenir. Aynı anda iki süreç (ör. iki retry_emails) aynı kaydı
    alamaz; böylece aynı e-posta iki kez gitmez (FR-13: her alıcıya tek e-posta).
    Gönderim sırasında süreç çökerse kayıt CLAIM_TIMEOUT sonra yeniden denenir.
    """
    return EmailNotification.objects.filter(
        pk=notification.pk, status=EmailStatus.PENDING, attempts=notification.attempts
    ).update(attempts=F("attempts") + 1, next_attempt_at=now + CLAIM_TIMEOUT)


def deliver(notification, now=None):
    """Tek bir e-postayı gönderir; başarısızsa sonraki denemeyi planlar ya da 'Başarısız' yapar."""
    now = now or timezone.now()
    if not _claim(notification, now):
        return None  # Başka bir süreç bu kaydı zaten işliyor ya da işledi.
    notification.attempts += 1
    try:
        send_mail(
            subject=notification.subject,
            message=notification.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient],  # FR-13: alıcılar birbirini görmez.
            fail_silently=False,
        )
    except Exception as exc:  # Hangi hata olursa olsun durum değişikliği etkilenmez.
        notification.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        if notification.attempts <= len(RETRY_DELAYS):
            notification.next_attempt_at = now + RETRY_DELAYS[notification.attempts - 1]
            logger.warning(
                "E-posta gönderilemedi, yeniden denenecek (bildirim #%s, deneme %s)",
                notification.report_id,
                notification.attempts,
            )
        else:
            notification.status = EmailStatus.FAILED
            notification.next_attempt_at = None
            logger.error("E-posta son denemede de gönderilemedi (bildirim #%s)", notification.report_id)
    else:
        notification.status = EmailStatus.SENT
        notification.sent_at = now
        notification.next_attempt_at = None
        notification.last_error = ""
    notification.save(update_fields=["status", "attempts", "next_attempt_at", "last_error", "sent_at"])
    return notification


def retry_due_emails(now=None, batch_size=100):
    """Zamanı gelmiş bekleyen e-postaları yeniden dener; gönderilmeye çalışılan kayıt sayısını döner."""
    due_at = now or timezone.now()
    due = EmailNotification.objects.filter(status=EmailStatus.PENDING, next_attempt_at__lte=due_at).order_by(
        "next_attempt_at", "id"
    )[:batch_size]
    # now verilmediyse her e-posta kendi gönderim anına göre planlanır (uzun süren turda kayma olmaz).
    return sum(1 for notification in due if deliver(notification, now=now) is not None)
