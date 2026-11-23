"""
Demo verisi: her rolden bir kullanıcı, birimler, kategoriler ve örnek bildirimler.
Kullanım: python manage.py seed_demo
Yalnızca geliştirme ve sunum içindir; gerçek ortamda çalıştırmayın.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role, User
from interactions.models import Comment, Support
from prioritization.models import Assessment
from reports import services
from reports.models import Category, ReportStatus
from units.models import Unit

DEMO_PASSWORD = "Kampus.2026"

USERS = [
    ("admin", "admin@kampusses.local", Role.ADMIN),
    ("ayse", "ayse@kampusses.local", Role.STUDENT),
    ("mehmet", "mehmet@kampusses.local", Role.STUDENT),
    ("bilgiislem", "bilgiislem@kampusses.local", Role.UNIT_MANAGER),
    ("yapiisleri", "yapiisleri@kampusses.local", Role.UNIT_MANAGER),
    ("kurul", "kurul@kampusses.local", Role.BOARD_MEMBER),
]

UNITS = [
    ("Bilgi İşlem", "Wi-Fi, bilgisayar laboratuvarları, öğrenci sistemleri", "bilgiislem"),
    ("Yapı İşleri", "Bina, asansör, aydınlatma, tesisat", "yapiisleri"),
    ("SKS", "Yemekhane, kantin, öğrenci etkinlik alanları", None),
]

CATEGORIES = [
    ("Bilişim", "Ağ, yazılım ve donanım sorunları", "Bilgi İşlem"),
    ("Bina ve Altyapı", "Asansör, aydınlatma, ısınma, tesisat", "Yapı İşleri"),
    ("Yemekhane", "Yemek kalitesi, kuyruk, hijyen", "SKS"),
    ("Ulaşım", "Servisler, otopark", None),
    ("Temizlik", "Tuvaletler, sınıflar, ortak alanlar", None),
]

REPORTS = [
    ("ayse", "B blok 3. kat Wi-Fi sürekli kopuyor", "Derslik ve koridorlarda eduroam bağlantısı birkaç dakikada bir kopuyor, online sınavlarda sorun oluyor.", "B Blok 3. kat", "Bilişim", ["wifi", "eduroam"]),
    ("mehmet", "A blok asansörü iki haftadır çalışmıyor", "Ana girişteki asansör arızalı; tekerlekli sandalye kullanan arkadaşlarımız üst katlara çıkamıyor.", "A Blok zemin kat", "Bina ve Altyapı", ["asansör", "erişilebilirlik"]),
    ("ayse", "Öğle saatlerinde yemekhane kuyruğu çok uzun", "12:00-13:00 arası kuyruk 30 dakikayı geçiyor, ders arasına yetişmiyor.", "Merkez yemekhane", "Yemekhane", ["kuyruk"]),
    ("mehmet", "Otoparka giden yolun aydınlatması yetersiz", "Akşam derslerinden sonra otopark yolu karanlık, güvenlik açısından endişe verici.", "Kuzey otopark yolu", "Bina ve Altyapı", ["aydınlatma", "güvenlik"]),
    ("ayse", "Bilgisayar laboratuvarında yazıcı çalışmıyor", "Lab 2'deki yazıcı bir haftadır kağıt sıkışması uyarısı veriyor.", "C Blok Lab 2", "Bilişim", ["yazıcı"]),
]


class Command(BaseCommand):
    help = "Geliştirme ve sunum için demo verisi oluşturur."

    @transaction.atomic
    def handle(self, *args, **options):
        users = {}
        for username, email, role in USERS:
            user, created = User.objects.get_or_create(email=email, defaults={"username": username, "role": role})
            if created:
                user.set_password(DEMO_PASSWORD)
                if role == Role.ADMIN:
                    user.is_staff = True
                    user.is_superuser = True
                user.save()
            users[username] = user

        units = {}
        for name, description, manager in UNITS:
            unit, _ = Unit.objects.get_or_create(name=name, defaults={"description": description})
            if manager:
                unit.members.add(users[manager])
            units[name] = unit

        categories = {}
        for name, description, unit_name in CATEGORIES:
            category, _ = Category.objects.get_or_create(
                name=name, defaults={"description": description, "default_unit": units.get(unit_name)}
            )
            categories[name] = category

        if not categories["Bilişim"].reports.exists():
            created = []
            for username, title, description, location, category, tags in REPORTS:
                from reports.models import Tag

                tag_objs = [Tag.objects.get_or_create(name=t)[0] for t in tags]
                created.append(
                    services.create_report(
                        users[username], title=title, description=description, location=location,
                        category=categories[category], tags=tag_objs,
                    )
                )
            wifi, elevator, queue, light, _printer = created
            for report, supporters in [(wifi, ["mehmet"]), (elevator, ["ayse"]), (light, ["ayse"])]:
                for name in supporters:
                    Support.objects.get_or_create(report=report, user=users[name])
            services.change_status(wifi, users["bilgiislem"], ReportStatus.IN_PROGRESS, "Erişim noktaları kontrol ediliyor.")
            Comment.objects.create(
                report=wifi, user=users["bilgiislem"], is_official=True,
                text="3. kattaki iki erişim noktası değiştirilecek, cuma gününe kadar tamamlanması planlanıyor.",
            )
            Comment.objects.create(report=elevator, user=users["ayse"], text="Ben de her gün merdiven kullanmak zorunda kalıyorum.")
            Assessment.objects.get_or_create(report=elevator, reviewer=users["kurul"], defaults={"urgency": 5, "impact": 5, "note": "Erişilebilirlik sorunu, öncelikli."})
            Assessment.objects.get_or_create(report=wifi, reviewer=users["kurul"], defaults={"urgency": 4, "impact": 4})

        self.stdout.write(self.style.SUCCESS("Demo verisi hazır. Tüm demo kullanıcılarının parolası: " + DEMO_PASSWORD))
        for username, email, role in USERS:
            self.stdout.write(f"  {Role(role).label:<16} {email}")
