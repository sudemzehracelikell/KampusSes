from rest_framework.test import APIClient

from django.test import TestCase

from accounts.models import Role, User
from units.models import Unit


class UnitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username="adm", email="adm@test.edu", password="x", role=Role.ADMIN)
        self.student = User.objects.create_user(username="ogr", email="ogr@test.edu", password="x")
        self.manager = User.objects.create_user(username="bim", email="bim@test.edu", password="x", role=Role.UNIT_MANAGER)
        self.unit = Unit.objects.create(name="Bilgi İşlem")

    def test_units_are_public_but_only_admin_writes(self):
        self.assertEqual(self.client.get("/api/units/").status_code, 200)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post("/api/units/", {"name": "Yeni"}, format="json").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post("/api/units/", {"name": "Yeni"}, format="json").status_code, 201)

    def test_only_unit_managers_can_be_members(self):
        self.client.force_authenticate(self.admin)
        bad = self.client.post(f"/api/units/{self.unit.pk}/members/", {"user_id": self.student.pk}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(f"/api/units/{self.unit.pk}/members/", {"user_id": self.manager.pk}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(len(ok.data["members"]), 1)
        removed = self.client.delete(f"/api/units/{self.unit.pk}/members/{self.manager.pk}/")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.unit.members.count(), 0)
