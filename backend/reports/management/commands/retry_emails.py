"""
Gönderilemeyen durum e-postalarını yeniden dener (NFR-14).

Kullanım:
    python manage.py retry_emails          # bir kez çalışır (zamanlanmış görev için)
    python manage.py retry_emails --loop   # her dakika tekrar çalışır (geliştirme ortamı için)
"""
import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from reports.models import EmailNotification, EmailStatus
from reports.notifications import retry_due_emails

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Zamanı gelmiş, gönderilemeyen durum e-postalarını yeniden dener (1, 5 ve 15 dakika sonra)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Durdurulana kadar her dakika çalış.")

    def run_once(self):
        tried = retry_due_emails()
        failed = EmailNotification.objects.filter(status=EmailStatus.FAILED).count()
        self.stdout.write(f"Yeniden denenen e-posta: {tried} · Başarısız (Admin panelinde): {failed}")

    def handle(self, *args, **options):
        if not options["loop"]:
            self.run_once()
            return
        self.stdout.write("Her dakika çalışıyor. Durdurmak için Ctrl+C.")
        try:
            while True:
                close_old_connections()
                try:
                    self.run_once()
                except Exception:  # Geçici hata (ör. veritabanı kilidi) döngüyü durdurmaz.
                    logger.exception("E-posta yeniden deneme turu başarısız; bir dakika sonra tekrar denenecek.")
                time.sleep(60)
        except KeyboardInterrupt:
            self.stdout.write("Durduruldu.")
