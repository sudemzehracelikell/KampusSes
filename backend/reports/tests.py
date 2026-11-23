from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User
from interactions.models import Support
from prioritization.models import Assessment
from reports import services
from reports.models import Category, Report, ReportStatus
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
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(sorted(mail.outbox[0].to), ["ogr2@test.edu", "ogr@test.edu"])

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
