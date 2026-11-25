import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from interactions.models import Comment, Support
from prioritization.models import Assessment
from reports import notifications, services
from reports.models import Category, EmailNotification, EmailStatus, Report, ReportMedia, ReportStatus
from units.models import Unit


class BaseReportTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.student = User.objects.create_user(username="ogr", email="ogr@test.edu", password="x")
        self.other = User.objects.create_user(username="ogr2", email="ogr2@test.edu", password="x")
        self.manager = User.objects.create_user(username="bim", email="bim@test.edu", password="x", role=Role.UNIT_MANAGER)
        self.other_manager = User.objects.create_user(username="yim", email="yim@test.edu", password="x", role=Role.UNIT_MANAGER)
        self.admin = User.objects.create_user(username="adm", email="adm@test.edu", password="x", role=Role.ADMIN)
        self.it = Unit.objects.create(name="Bilgi İşlem")
        self.it.members.add(self.manager)
        self.facilities = Unit.objects.create(name="Yapı İşleri")
        self.facilities.members.add(self.other_manager)
        self.cat_it = Category.objects.create(name="Bilişim", default_unit=self.it)
        self.cat_free = Category.objects.create(name="Ulaşım")

    def payload(self, **overrides):
        data = {
            "title": "Wi-Fi sürekli kopuyor",
            "description": "Üçüncü katta bağlantı birkaç dakikada bir kopuyor.",
            "location": "B Blok 3. kat",
            "category": self.cat_it.pk,
            "tags": ["wifi", "#Eduroam"],
        }
        data.update(overrides)
        return data

    def create(self, user=None, **overrides):
        self.client.force_authenticate(user or self.student)
        res = self.client.post("/api/reports/", self.payload(**overrides), format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return Report.objects.get(pk=res.data["id"])


class ReportCreationTests(BaseReportTest):
    def test_anonymous_cannot_create(self):
        res = self.client.post("/api/reports/", self.payload(), format="json")
        self.assertEqual(res.status_code, 401)

    def test_auto_assign_to_category_unit(self):
        report = self.create()
        self.assertEqual(report.assigned_unit, self.it)
        self.assertEqual(report.status, ReportStatus.ASSIGNED)
        self.assertEqual(report.status_updates.count(), 2)
        self.assertEqual(sorted(report.tags.values_list("name", flat=True)), ["eduroam", "wifi"])

    def test_category_without_unit_stays_new(self):
        report = self.create(category=self.cat_free.pk)
        self.assertIsNone(report.assigned_unit)
        self.assertEqual(report.status, ReportStatus.NEW)

    def test_validation(self):
        self.client.force_authenticate(self.student)
        res = self.client.post("/api/reports/", self.payload(title="kısa", description="az"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("title", res.data)
        self.assertIn("description", res.data)

    def test_public_list_hides_creator_email(self):
        self.create()
        self.client.force_authenticate(None)
        res = self.client.get("/api/reports/")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("email", res.data["results"][0]["created_by"])

    def test_similar_reports(self):
        self.create()
        res = self.client.get("/api/reports/similar/", {"category": self.cat_it.pk, "location": "b blok"})
        self.assertEqual(len(res.data), 1)
        res = self.client.get("/api/reports/similar/", {"category": self.cat_free.pk, "location": "b blok"})
        self.assertEqual(len(res.data), 0)


class OwnerPermissionTests(BaseReportTest):
    def test_owner_can_edit_until_in_progress(self):
        report = self.create()
        res = self.client.patch(f"/api/reports/{report.pk}/", {"title": "Wi-Fi bağlantı sorunu"}, format="json")
        self.assertEqual(res.status_code, 200)
        services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "İnceleniyor")
        res = self.client.patch(f"/api/reports/{report.pk}/", {"title": "Değişmemeli"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_other_user_cannot_edit_or_delete(self):
        report = self.create()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.patch(f"/api/reports/{report.pk}/", {"title": "Başkası değiştirdi"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/reports/{report.pk}/").status_code, 403)

    def test_admin_delete_is_soft(self):
        report = self.create()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(f"/api/reports/{report.pk}/").status_code, 204)
        report.refresh_from_db()
        self.assertTrue(report.is_removed)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(f"/api/reports/{report.pk}/").status_code, 404)


class WithdrawTests(BaseReportTest):
    """FR-06: Geri çekilen kayıt listeden kalkar, geçmişi korunur."""

    def withdraw(self, report, user=None):
        self.client.force_authenticate(user or self.student)
        return self.client.delete(f"/api/reports/{report.pk}/")

    def test_withdraw_keeps_record_and_history(self):
        report = self.create()
        history_before = report.status_updates.count()
        self.assertEqual(self.withdraw(report).status_code, 204)
        # Kayıt silinmedi, geri çekildi olarak işaretlendi.
        report.refresh_from_db()
        self.assertTrue(report.is_withdrawn)
        self.assertIsNotNone(report.withdrawn_at)
        self.assertEqual(report.status, ReportStatus.ASSIGNED)
        # Eski geçmiş duruyor ve geri çekme de geçmişe yazıldı.
        self.assertEqual(report.status_updates.count(), history_before + 1)
        last = report.status_updates.last()
        self.assertEqual(last.user, self.student)
        self.assertIn("geri çekildi", last.note)

    def test_withdrawn_report_leaves_lists(self):
        report = self.create()
        self.withdraw(report)
        for user in (None, self.student, self.admin):
            self.client.force_authenticate(user)
            ids = [r["id"] for r in self.client.get("/api/reports/").data["results"]]
            self.assertNotIn(report.pk, ids)
        # "Bildirimlerim" (FR-18) sahibinin kendi oturumuyla kontrol edilir.
        self.client.force_authenticate(self.student)
        mine = self.client.get("/api/reports/", {"mine": "true"})
        self.assertEqual(mine.data["count"], 0)
        # Birim panelinde de görünmez.
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get("/api/reports/", {"my_units": "true"}).data["count"], 0)
        similar = self.client.get("/api/reports/similar/", {"category": self.cat_it.pk, "location": "b blok"})
        self.assertEqual(similar.data, [])
        self.assertEqual(self.client.get(f"/api/units/{self.it.pk}/").data["open_report_count"], 0)

    def test_owner_and_admin_can_still_see_history(self):
        report = self.create()
        self.withdraw(report)
        for user in (self.student, self.admin):
            self.client.force_authenticate(user)
            res = self.client.get(f"/api/reports/{report.pk}/")
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.data["is_withdrawn"])
            self.assertEqual(len(res.data["status_updates"]), 3)
            self.assertFalse(res.data["permissions"]["can_edit"])
            self.assertFalse(res.data["permissions"]["can_delete"])
            self.assertFalse(res.data["permissions"]["can_support"])

    def test_others_get_404(self):
        report = self.create()
        self.withdraw(report)
        for user in (None, self.other, self.manager):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(f"/api/reports/{report.pk}/").status_code, 404)

    def test_withdrawn_report_is_read_only(self):
        report = self.create()
        self.withdraw(report)
        # Sahibi tekrar düzenleyemez veya geri çekemez.
        res = self.client.patch(f"/api/reports/{report.pk}/", {"title": "Yeni başlık"}, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.withdraw(report).status_code, 404)
        # Destek, yorum, durum değişikliği ve kurul puanı reddedilir.
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f"/api/reports/{report.pk}/support/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/reports/{report.pk}/comments/", {"text": "Merhaba"}).status_code, 404)
        self.client.force_authenticate(self.manager)
        payload = {"status": "IN_PROGRESS", "note": "x"}
        res = self.client.post(f"/api/reports/{report.pk}/status/", payload, format="json")
        self.assertEqual(res.status_code, 404)
        board = User.objects.create_user(username="kurul", email="kurul@test.edu", password="x", role=Role.BOARD_MEMBER)
        self.client.force_authenticate(board)
        res = self.client.put(f"/api/reports/{report.pk}/assessment/", {"urgency": 3, "impact": 3}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_cannot_withdraw_after_in_progress(self):
        report = self.create()
        services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "İnceleniyor")
        self.assertEqual(self.withdraw(report).status_code, 403)
        report.refresh_from_db()
        self.assertFalse(report.is_withdrawn)

    def test_other_user_cannot_withdraw(self):
        report = self.create()
        self.assertEqual(self.withdraw(report, self.other).status_code, 403)
        report.refresh_from_db()
        self.assertFalse(report.is_withdrawn)

    def test_service_rechecks_status(self):
        # Yetki kontrolünden sonra durum değişmiş olsa bile servis geri çekmeyi reddeder.
        report = self.create()
        services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "İnceleniyor")
        with self.assertRaises(services.BusinessRuleError):
            services.withdraw_report(report, self.student)
        services.change_status(report, self.manager, ReportStatus.REJECTED, "Mükerrer")
        with self.assertRaises(services.BusinessRuleError):
            services.withdraw_report(report, self.student)

    def test_service_rejects_double_withdraw(self):
        report = self.create()
        services.withdraw_report(report, self.student)
        with self.assertRaises(services.BusinessRuleError):
            services.withdraw_report(report, self.student)

    def test_new_status_report_can_be_withdrawn(self):
        report = self.create(category=self.cat_free.pk)
        self.assertEqual(report.status, ReportStatus.NEW)
        self.assertEqual(self.withdraw(report).status_code, 204)

    def test_closed_report_cannot_be_withdrawn(self):
        for final in (ReportStatus.RESOLVED, ReportStatus.REJECTED):
            report = self.create()
            if final == ReportStatus.RESOLVED:
                services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "İnceleniyor")
            services.change_status(report, self.manager, final, "Kapatıldı")
            self.assertEqual(self.withdraw(report).status_code, 403)
            report.refresh_from_db()
            self.assertFalse(report.is_withdrawn)

    def test_withdrawn_report_media_and_comments_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            report = self.create()
            media = ReportMedia.objects.create(report=report, file=SimpleUploadedFile("foto.png", b"\x89PNG"))
            comment = Comment.objects.create(report=report, user=self.student, text="Ek bilgi")
            self.withdraw(report)
            self.assertEqual(self.client.delete(f"/api/media/{media.pk}/").status_code, 404)
            self.assertEqual(self.client.delete(f"/api/comments/{comment.pk}/").status_code, 404)
            self.client.force_authenticate(self.admin)
            self.assertEqual(self.client.delete(f"/api/comments/{comment.pk}/").status_code, 404)
            self.assertTrue(ReportMedia.objects.filter(pk=media.pk).exists())
            self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_withdrawn_report_cannot_be_reassigned_or_get_media(self):
        report = self.create()
        self.withdraw(report)
        res = self.client.post(f"/api/reports/{report.pk}/media/", {"file": SimpleUploadedFile("a.png", b"x")})
        self.assertEqual(res.status_code, 404)
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/reports/{report.pk}/assign/", {"unit": self.facilities.pk}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_admin_own_report_follows_owner_rule(self):
        report = self.create(user=self.admin)
        res = self.client.get(f"/api/reports/{report.pk}/")
        self.assertTrue(res.data["permissions"]["can_delete"])
        services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "İnceleniyor")
        res = self.client.get(f"/api/reports/{report.pk}/")
        self.assertFalse(res.data["permissions"]["can_delete"])  # "Geri Çek" butonu gösterilmez.
        self.assertEqual(self.withdraw(report, self.admin).status_code, 403)
        report.refresh_from_db()
        self.assertFalse(report.is_withdrawn)
        self.assertFalse(report.is_removed)

    def test_admin_can_withdraw_own_assigned_report(self):
        report = self.create(user=self.admin)
        self.assertEqual(self.withdraw(report, self.admin).status_code, 204)
        report.refresh_from_db()
        self.assertTrue(report.is_withdrawn)
        self.assertFalse(report.is_removed)

    def test_services_reject_withdrawn_report(self):
        # Kilit altında yapılan kontrol: eşzamanlı geri çekmeden sonra gelen işlem reddedilir.
        report = self.create()
        services.withdraw_report(report, self.student)
        with self.assertRaises(services.BusinessRuleError):
            services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "İnceleniyor")
        with self.assertRaises(services.BusinessRuleError):
            services.reassign(report, self.manager, self.facilities, "Aktarım")
        with self.assertRaises(services.BusinessRuleError):
            services.update_report(report, self.student, title="Değişmemeli")
        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.ASSIGNED)
        self.assertEqual(report.assigned_unit, self.it)

    def test_edit_does_not_undo_concurrent_withdraw(self):
        # Düzenleme bellekteki eski nesneyle yapılsa bile geri çekme ezilmez.
        report = self.create()
        stale = Report.objects.get(pk=report.pk)
        services.withdraw_report(report, self.student)
        with self.assertRaises(services.BusinessRuleError):
            services.update_report(stale, self.student, title="Eski nesneyle düzenleme")
        report.refresh_from_db()
        self.assertTrue(report.is_withdrawn)

    def test_edit_writes_only_changed_fields(self):
        report = self.create()
        stale = Report.objects.get(pk=report.pk)
        services.change_status(report, self.manager, ReportStatus.REJECTED, "Mükerrer")
        # Admin kapalı kaydı da düzenleyebilir; ama eski nesnedeki durum veritabanına geri yazılmaz.
        services.update_report(stale, self.admin, title="Admin düzeltmesi")
        report.refresh_from_db()
        self.assertEqual(report.title, "Admin düzeltmesi")
        self.assertEqual(report.status, ReportStatus.REJECTED)


class StatusTransitionTests(BaseReportTest):
    def test_only_assigned_unit_staff_can_change_status(self):
        report = self.create()
        for user in (self.student, self.other_manager):
            self.client.force_authenticate(user)
            res = self.client.post(f"/api/reports/{report.pk}/status/", {"status": "IN_PROGRESS", "note": "x"}, format="json")
            self.assertEqual(res.status_code, 403)
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/reports/{report.pk}/status/", {"status": "IN_PROGRESS", "note": "Bakılıyor"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "IN_PROGRESS")

    def test_invalid_transition_rejected(self):
        report = self.create()
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/reports/{report.pk}/status/", {"status": "RESOLVED", "note": "Bitti"}, format="json")
        self.assertEqual(res.status_code, 400)  # ASSIGNED -> RESOLVED atlanamaz.

    def test_note_is_required(self):
        report = self.create()
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/reports/{report.pk}/status/", {"status": "IN_PROGRESS", "note": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_closed_report_cannot_change(self):
        report = self.create()
        services.change_status(report, self.manager, ReportStatus.REJECTED, "Mükerrer")
        report.refresh_from_db()
        self.assertFalse(services.can_transition(report.status, ReportStatus.IN_PROGRESS))
        with self.assertRaises(services.BusinessRuleError):
            services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "Tekrar aç")

    def test_status_change_emails_owner_and_supporters(self):
        report = self.create()
        Support.objects.create(report=report, user=self.other)
        mail.outbox = []
        self.client.force_authenticate(self.manager)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/reports/{report.pk}/status/", {"status": "IN_PROGRESS", "note": "Bakılıyor"}, format="json")
        # FR-13: Her alıcıya ayrı e-posta gider; alıcılar birbirinin adresini görmez.
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["ogr2@test.edu", "ogr@test.edu"])
        self.assertTrue(all(len(m.to) == 1 for m in mail.outbox))

    def test_reassign_moves_report_to_other_unit(self):
        report = self.create()
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/reports/{report.pk}/assign/", {"unit": self.facilities.pk, "note": "Bizim işimiz değil"}, format="json")
        self.assertEqual(res.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.assigned_unit, self.facilities)
        # Eski birim artık yönetemez, yeni birim yönetebilir.
        self.assertFalse(services.user_manages_report(self.manager, report))
        self.assertTrue(services.user_manages_report(self.other_manager, report))


class PriorityTests(BaseReportTest):
    def test_priority_ordering_uses_board_score_and_supports(self):
        low = self.create(title="Düşük öncelikli sorun")
        high = self.create(title="Yüksek öncelikli sorun")
        board = User.objects.create_user(username="kurul", email="kurul@test.edu", password="x", role=Role.BOARD_MEMBER)
        Assessment.objects.create(report=high, reviewer=board, urgency=5, impact=5)
        Support.objects.create(report=low, user=self.other)
        res = self.client.get("/api/reports/", {"ordering": "-priority_score"})
        ids = [r["id"] for r in res.data["results"]]
        self.assertEqual(ids[:2], [high.pk, low.pk])
        top = res.data["results"][0]
        self.assertEqual(top["priority_score"], 50.0)  # 5 × 10 + 0 destek

    def test_report_example_score(self):
        # Faz 2 raporundaki örnek: (4, 5) ve (2, 3) puanları, 20 destek → 3,5 × 10 + 20 = 55.
        report = self.create()
        for i, (urgency, impact) in enumerate([(4, 5), (2, 3)]):
            board = User.objects.create_user(
                username=f"kurul{i}", email=f"kurul{i}@test.edu", password="x", role=Role.BOARD_MEMBER
            )
            Assessment.objects.create(report=report, reviewer=board, urgency=urgency, impact=impact)
        supporters = [User(username=f"d{i}", email=f"d{i}@test.edu") for i in range(20)]
        User.objects.bulk_create(supporters)
        supporters = User.objects.filter(username__startswith="d")
        Support.objects.bulk_create([Support(report=report, user=u) for u in supporters])
        res = self.client.get(f"/api/reports/{report.pk}/")
        self.assertEqual(res.data["board_score"], 3.5)
        self.assertEqual(res.data["priority_score"], 55.0)
        self.assertFalse(res.data["awaiting_assessment"])

    def test_equal_scores_older_first(self):
        # FR-15: Eşitlikte eski kayıt önce gelir.
        older = self.create(title="Önce açılan bildirim")
        newer = self.create(title="Sonra açılan bildirim")
        res = self.client.get("/api/reports/", {"ordering": "-priority_score"})
        ids = [r["id"] for r in res.data["results"]]
        self.assertEqual(ids, [older.pk, newer.pk])
        # Varsayılan liste (en yeni) etkilenmez.
        res = self.client.get("/api/reports/")
        self.assertEqual([r["id"] for r in res.data["results"]], [newer.pk, older.pk])

    def ranking(self):
        res = self.client.get("/api/reports/", {"ordering": "-priority_score"})
        return [(r["id"], r["priority_score"]) for r in res.data["results"]]

    def test_score_follows_support_and_assessment_changes(self):
        # FR-15: Puan veya destek değişince skor ve sıralama güncellenir.
        older = self.create(title="Önce açılan bildirim")
        newer = self.create(title="Sonra açılan bildirim")
        self.client.force_authenticate(self.other)
        self.client.post(f"/api/reports/{newer.pk}/support/")
        self.assertEqual(self.ranking(), [(newer.pk, 1.0), (older.pk, 0.0)])
        board = User.objects.create_user(username="kurul", email="kurul@test.edu", password="x", role=Role.BOARD_MEMBER)
        self.client.force_authenticate(board)
        self.client.put(f"/api/reports/{older.pk}/assessment/", {"urgency": 1, "impact": 1}, format="json")
        self.assertEqual(self.ranking(), [(older.pk, 10.0), (newer.pk, 1.0)])
        self.client.put(f"/api/reports/{older.pk}/assessment/", {"urgency": 5, "impact": 4}, format="json")
        self.assertEqual(self.ranking()[0], (older.pk, 45.0))
        self.client.force_authenticate(self.other)
        self.client.delete(f"/api/reports/{newer.pk}/support/")
        self.assertEqual(self.ranking()[1], (newer.pk, 0.0))

    def test_equal_scores_from_different_parts(self):
        # 1 × 10 + 0 destek = 10 ile 0 × 10 + 10 destek = 10 eşittir; eski kayıt önce gelir.
        older = self.create(title="Kurul puanlı bildirim")
        newer = self.create(title="Destekli bildirim")
        board = User.objects.create_user(username="kurul", email="kurul@test.edu", password="x", role=Role.BOARD_MEMBER)
        Assessment.objects.create(report=older, reviewer=board, urgency=1, impact=1)
        User.objects.bulk_create([User(username=f"d{i}", email=f"d{i}@test.edu") for i in range(10)])
        supporters = User.objects.filter(username__startswith="d")
        Support.objects.bulk_create([Support(report=newer, user=u) for u in supporters])
        self.assertEqual(self.ranking(), [(older.pk, 10.0), (newer.pk, 10.0)])

    def test_awaiting_assessment_until_board_scores(self):
        # FR-15: Puanı olmayan kayıtta ortalama 0 alınır ve "Değerlendirme bekliyor" gösterilir.
        report = self.create()
        res = self.client.get(f"/api/reports/{report.pk}/")
        self.assertTrue(res.data["awaiting_assessment"])
        self.assertEqual(res.data["board_score"], 0)
        board = User.objects.create_user(username="kurul", email="kurul@test.edu", password="x", role=Role.BOARD_MEMBER)
        Assessment.objects.create(report=report, reviewer=board, urgency=1, impact=1)
        listed = self.client.get("/api/reports/").data["results"][0]
        self.assertFalse(listed["awaiting_assessment"])
        self.assertEqual(listed["priority_score"], 10.0)  # sınır: en düşük puan 1 → 1 × 10 + 0


class MediaTests(BaseReportTest):
    @override_settings(MEDIA_ROOT="/tmp/kampusses-test-media")
    def test_upload_rules(self):
        report = self.create()
        ok = self.client.post(
            f"/api/reports/{report.pk}/media/",
            {"file": SimpleUploadedFile("foto.png", b"\x89PNG fake", content_type="image/png")},
            format="multipart",
        )
        self.assertEqual(ok.status_code, 201)
        bad = self.client.post(
            f"/api/reports/{report.pk}/media/",
            {"file": SimpleUploadedFile("script.exe", b"MZ", content_type="application/octet-stream")},
            format="multipart",
        )
        self.assertEqual(bad.status_code, 400)


class EmailNotificationTests(BaseReportTest):
    """FR-13 ve NFR-14: tek e-posta, hata durumu geri almaz, 1-5-15 dakika yeniden deneme."""

    def change_status(self, report, new_status=ReportStatus.IN_PROGRESS):
        self.client.force_authenticate(self.manager)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(
                f"/api/reports/{report.pk}/status/", {"status": new_status, "note": "Bakılıyor"}, format="json"
            )
        self.assertEqual(res.status_code, 200, res.data)
        return res

    def test_one_email_per_recipient(self):
        report = self.create()
        Support.objects.create(report=report, user=self.other)
        # Aynı adres farklı yazılsa da tek e-posta gider.
        twin = User.objects.create_user(username="ikiz", email="OGR2@test.edu ", password="x")
        Support.objects.create(report=report, user=twin)
        mail.outbox = []
        self.change_status(report)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["ogr2@test.edu", "ogr@test.edu"])
        self.assertEqual(EmailNotification.objects.filter(status=EmailStatus.SENT).count(), 2)

    def test_failure_does_not_undo_status_change(self):
        report = self.create()
        with mock.patch("reports.notifications.send_mail", side_effect=OSError("SMTP kapalı")):
            res = self.change_status(report)
        self.assertEqual(res.data["status"], "IN_PROGRESS")
        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.IN_PROGRESS)
        self.assertEqual(report.status_updates.last().new_status, ReportStatus.IN_PROGRESS)
        notification = EmailNotification.objects.get(report=report)
        self.assertEqual(notification.status, EmailStatus.PENDING)
        self.assertEqual(notification.attempts, 1)
        self.assertIn("SMTP kapalı", notification.last_error)

    def test_retries_after_1_5_15_minutes_then_fails(self):
        report = self.create()
        start = timezone.now()
        with mock.patch("reports.notifications.send_mail", side_effect=OSError("SMTP kapalı")) as send:
            with mock.patch("reports.notifications.timezone.now", return_value=start):
                self.change_status(report)
            notification = EmailNotification.objects.get(report=report)
            self.assertEqual(notification.next_attempt_at, start + timedelta(minutes=1))
            # Süresi dolmadan yeniden denenmez (sınır: 59 saniye).
            self.assertEqual(notifications.retry_due_emails(now=start + timedelta(seconds=59)), 0)
            moment = start
            for minutes, attempt in ((1, 2), (5, 3), (15, 4)):
                # Her başarısız denemeden sonraki bekleme: 1, 5, 15 dakika.
                self.assertEqual(notification.next_attempt_at, moment + timedelta(minutes=minutes))
                moment = notification.next_attempt_at
                self.assertEqual(notifications.retry_due_emails(now=moment), 1)
                notification.refresh_from_db()
                self.assertEqual(notification.attempts, attempt)
            self.assertEqual(send.call_count, 4)
        # Son deneme de başarısız: kayıt "Başarısız" olur, artık denenmez.
        self.assertEqual(notification.status, EmailStatus.FAILED)
        self.assertIsNone(notification.next_attempt_at)
        self.assertEqual(notifications.retry_due_emails(now=moment + timedelta(days=1)), 0)

    def test_retry_succeeds_when_service_recovers(self):
        report = self.create()
        mail.outbox = []
        with mock.patch("reports.notifications.send_mail", side_effect=OSError("SMTP kapalı")):
            self.change_status(report)
        self.assertEqual(len(mail.outbox), 0)
        later = timezone.now() + timedelta(minutes=2)
        self.assertEqual(notifications.retry_due_emails(now=later), 1)
        notification = EmailNotification.objects.get(report=report)
        self.assertEqual(notification.status, EmailStatus.SENT)
        self.assertEqual(notification.attempts, 2)
        self.assertEqual(len(mail.outbox), 1)
        # Başarıdan sonra hata ve bekleyen deneme bilgisi temizlenir.
        self.assertEqual(notification.last_error, "")
        self.assertIsNone(notification.next_attempt_at)
        self.assertIsNotNone(notification.sent_at)

    def test_retry_command_runs(self):
        out = StringIO()
        call_command("retry_emails", stdout=out)
        self.assertIn("Yeniden denenen e-posta: 0", out.getvalue())

    def make_notification(self, report, **fields):
        data = {"recipient": "ogr@test.edu", "subject": "Konu", "body": "İleti", "next_attempt_at": timezone.now()}
        data.update(fields)
        return EmailNotification.objects.create(report=report, **data)

    def test_retry_command_sends_due_and_counts_failed(self):
        report = self.create()
        due = self.make_notification(report, attempts=1, next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.make_notification(report, recipient="ogr2@test.edu", attempts=4, status=EmailStatus.FAILED,
                               next_attempt_at=None)
        mail.outbox = []
        out = StringIO()
        call_command("retry_emails", stdout=out)
        self.assertIn("Yeniden denenen e-posta: 1 · Başarısız (Admin panelinde): 1", out.getvalue())
        due.refresh_from_db()
        self.assertEqual(due.status, EmailStatus.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_partial_failure_retries_only_failed_recipient(self):
        report = self.create()
        Support.objects.create(report=report, user=self.other)
        mail.outbox = []
        real_send = notifications.send_mail

        def fail_for_owner(*args, **kwargs):
            if kwargs["recipient_list"] == ["ogr@test.edu"]:
                raise OSError("SMTP reddetti")
            return real_send(*args, **kwargs)

        with mock.patch("reports.notifications.send_mail", side_effect=fail_for_owner):
            self.change_status(report)
        self.assertEqual([m.to for m in mail.outbox], [["ogr2@test.edu"]])
        self.assertEqual(notifications.retry_due_emails(now=timezone.now() + timedelta(minutes=2)), 1)
        # Başarılı alıcıya ikinci e-posta gitmez; yalnızca başarısız olan yeniden denenir.
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["ogr2@test.edu", "ogr@test.edu"])
        self.assertEqual(EmailNotification.objects.filter(status=EmailStatus.SENT).count(), 2)

    def test_owner_supporting_own_report_and_blank_email(self):
        report = self.create()
        Support.objects.create(report=report, user=self.student)  # Bildiren kendi kaydını destekledi.
        blank = User.objects.create_user(username="bos", email="", password="x")
        Support.objects.create(report=report, user=blank)
        self.assertEqual(notifications.status_change_recipients(report), ["ogr@test.edu"])

    def test_no_email_when_status_change_rejected(self):
        report = self.create()
        self.client.force_authenticate(self.manager)
        payload = {"status": "RESOLVED", "note": "Adım atlama"}
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(f"/api/reports/{report.pk}/status/", payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(EmailNotification.objects.exists())

    def test_interrupted_send_is_not_lost(self):
        # Gönderimi hiç denenmeden kalan kayıt (ör. sunucu kapandı) yeniden deneme turunda bulunur.
        report = self.create()
        orphan = self.make_notification(report)
        self.assertEqual(notifications.retry_due_emails(now=timezone.now() + timedelta(seconds=1)), 1)
        orphan.refresh_from_db()
        self.assertEqual(orphan.status, EmailStatus.SENT)

    def test_same_email_is_not_sent_twice_by_parallel_runs(self):
        # İki süreç aynı kaydı aynı anda alırsa yalnızca biri gönderir (FR-13: tek e-posta).
        report = self.create()
        first = self.make_notification(report)
        second = EmailNotification.objects.get(pk=first.pk)
        mail.outbox = []
        self.assertIsNotNone(notifications.deliver(first))
        self.assertIsNone(notifications.deliver(second))
        self.assertEqual(len(mail.outbox), 1)


class HiddenAndWithdrawnAccessTests(BaseReportTest):
    """FR-06 ve FR-16: geri çekilen ve gizlenen kayıtlara diğer uçlardan da erişilemez."""

    def test_assessment_not_readable_after_withdraw_or_hide(self):
        board = User.objects.create_user(username="kurul", email="kurul@test.edu", password="x", role=Role.BOARD_MEMBER)
        withdrawn = self.create()
        hidden = self.create(title="Gizlenecek bildirim")
        for report in (withdrawn, hidden):
            Assessment.objects.create(report=report, reviewer=board, urgency=3, impact=3)
        services.withdraw_report(withdrawn, self.student)
        Report.objects.filter(pk=hidden.pk).update(is_removed=True)
        self.client.force_authenticate(board)
        for report in (withdrawn, hidden):
            self.assertEqual(self.client.get(f"/api/reports/{report.pk}/assessment/").status_code, 404)

    def test_hidden_report_comments_and_media_only_admin(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            report = self.create()
            media = ReportMedia.objects.create(report=report, file=SimpleUploadedFile("foto.png", b"\x89PNG"))
            comment = Comment.objects.create(report=report, user=self.student, text="Ek bilgi")
            Report.objects.filter(pk=report.pk).update(is_removed=True)
            # Sahibi gizlenen kaydın dosyasını ve yorumunu silemez.
            self.assertEqual(self.client.delete(f"/api/media/{media.pk}/").status_code, 404)
            self.assertEqual(self.client.delete(f"/api/comments/{comment.pk}/").status_code, 404)
            # Admin her yorumu silebilir (FR-10).
            self.client.force_authenticate(self.admin)
            self.assertEqual(self.client.delete(f"/api/comments/{comment.pk}/").status_code, 204)

    def test_services_reject_hidden_report_for_non_admin(self):
        report = self.create()
        Report.objects.filter(pk=report.pk).update(is_removed=True)
        with self.assertRaises(services.BusinessRuleError):
            services.change_status(report, self.manager, ReportStatus.IN_PROGRESS, "İnceleniyor")
        with self.assertRaises(services.BusinessRuleError):
            services.update_report(report, self.student, title="Gizli kayıt düzenlemesi")
        with self.assertRaises(services.BusinessRuleError):
            services.withdraw_report(report, self.student)
        # Admin gizlenen kayıt üzerinde işlem yapabilir.
        services.change_status(report, self.admin, ReportStatus.REJECTED, "Uygunsuz içerik")
        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.REJECTED)

    def test_tags_only_edit_updates_timestamp(self):
        report = self.create()
        before = report.updated_at
        res = self.client.patch(f"/api/reports/{report.pk}/", {"tags": ["asansor"]}, format="json")
        self.assertEqual(res.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(list(report.tags.values_list("name", flat=True)), ["asansor"])
        self.assertGreater(report.updated_at, before)
