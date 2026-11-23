from rest_framework.test import APIClient

from accounts.models import Role, User
from reports import services
from reports.models import ReportStatus
from reports.tests import BaseReportTest


class SupportTests(BaseReportTest):
    def test_support_once_and_undo(self):
        report = self.create()
        self.client.force_authenticate(self.other)
        first = self.client.post(f"/api/reports/{report.pk}/support/")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["support_count"], 1)
        second = self.client.post(f"/api/reports/{report.pk}/support/")
        self.assertEqual(second.status_code, 409)  # Çift destek yok (NFR-06).
        undo = self.client.delete(f"/api/reports/{report.pk}/support/")
        self.assertEqual(undo.data["support_count"], 0)

    def test_anonymous_cannot_support(self):
        report = self.create()
        self.assertEqual(APIClient().post(f"/api/reports/{report.pk}/support/").status_code, 401)

    def test_closed_report_cannot_be_supported(self):
        report = self.create()
        services.change_status(report, self.manager, ReportStatus.REJECTED, "Mükerrer")
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f"/api/reports/{report.pk}/support/").status_code, 403)


class CommentTests(BaseReportTest):
    def test_unit_staff_comment_is_official(self):
        report = self.create()
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/reports/{report.pk}/comments/", {"text": "İnceliyoruz."}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data["is_official"])
        self.client.force_authenticate(self.other)
        res = self.client.post(f"/api/reports/{report.pk}/comments/", {"text": "Ben de yaşıyorum.", "is_official": True}, format="json")
        self.assertFalse(res.data["is_official"])  # İstemci bu alanı belirleyemez.

    def test_comment_validation_and_delete_rules(self):
        report = self.create()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f"/api/reports/{report.pk}/comments/", {"text": "  "}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"/api/reports/{report.pk}/comments/", {"text": "a" * 1001}, format="json").status_code, 400)
        comment_id = self.client.post(f"/api/reports/{report.pk}/comments/", {"text": "Yorum"}, format="json").data["id"]
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.delete(f"/api/comments/{comment_id}/").status_code, 403)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.delete(f"/api/comments/{comment_id}/").status_code, 204)

    def test_no_comments_on_closed_report(self):
        report = self.create()
        services.change_status(report, self.manager, ReportStatus.REJECTED, "Mükerrer")
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f"/api/reports/{report.pk}/comments/", {"text": "Geç kaldım"}, format="json").status_code, 403)


class AssessmentTests(BaseReportTest):
    def setUp(self):
        super().setUp()
        self.board = User.objects.create_user(username="kurul", email="kurul@test.edu", password="x", role=Role.BOARD_MEMBER)

    def test_only_board_members_can_assess(self):
        report = self.create()
        self.client.force_authenticate(self.manager)
        res = self.client.put(f"/api/reports/{report.pk}/assessment/", {"urgency": 3, "impact": 3}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_score_range_and_single_assessment(self):
        report = self.create()
        self.client.force_authenticate(self.board)
        bad = self.client.put(f"/api/reports/{report.pk}/assessment/", {"urgency": 6, "impact": 0}, format="json")
        self.assertEqual(bad.status_code, 400)
        first = self.client.put(f"/api/reports/{report.pk}/assessment/", {"urgency": 2, "impact": 3}, format="json")
        self.assertEqual(first.status_code, 201)
        second = self.client.put(f"/api/reports/{report.pk}/assessment/", {"urgency": 5, "impact": 4}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(report.assessments.count(), 1)
        res = self.client.get("/api/reports/", {"unassessed": "true"})
        self.assertEqual(res.data["count"], 0)
