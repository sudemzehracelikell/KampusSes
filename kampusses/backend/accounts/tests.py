from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User


class AuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(username="ayse", email="ayse@test.edu", password="Guclu.Parola1")

    def test_password_is_hashed(self):
        self.assertNotEqual(self.user.password, "Guclu.Parola1")
        self.assertTrue(self.user.password.startswith("pbkdf2_"))

    def test_register_creates_student_and_never_returns_password(self):
        res = self.client.post(
            "/api/auth/register/",
            {"username": "mehmet", "email": "Mehmet@Test.edu", "password": "Baska.Parola9", "role": "ADMIN"},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertNotIn("password", res.data)
        user = User.objects.get(email="mehmet@test.edu")
        self.assertEqual(user.role, Role.STUDENT)  # Kayıtta rol seçilemez.

    def test_register_rejects_weak_password_and_duplicate_email(self):
        weak = self.client.post("/api/auth/register/", {"username": "x", "email": "x@test.edu", "password": "12345678"}, format="json")
        self.assertEqual(weak.status_code, 400)
        dup = self.client.post("/api/auth/register/", {"username": "y", "email": "AYSE@test.edu", "password": "Guclu.Parola2"}, format="json")
        self.assertEqual(dup.status_code, 400)

    @override_settings(ALLOWED_EMAIL_DOMAINS=["istun.edu.tr"])
    def test_register_enforces_university_domain(self):
        res = self.client.post("/api/auth/register/", {"username": "z", "email": "z@gmail.com", "password": "Guclu.Parola3"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.data)

    def test_login_returns_token_and_generic_error(self):
        ok = self.client.post("/api/auth/login/", {"email": "ayse@test.edu", "password": "Guclu.Parola1"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertIn("token", ok.data)
        self.assertNotIn("password", ok.data["user"])
        bad = self.client.post("/api/auth/login/", {"email": "ayse@test.edu", "password": "yanlis"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.data["detail"], "E-posta veya parola hatalı.")

    def test_login_locks_after_five_failures(self):
        for _ in range(5):
            self.client.post("/api/auth/login/", {"email": "ayse@test.edu", "password": "yanlis"}, format="json")
        res = self.client.post("/api/auth/login/", {"email": "ayse@test.edu", "password": "Guclu.Parola1"}, format="json")
        self.assertEqual(res.status_code, 429)

    def test_me_requires_token(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/auth/me/").data["email"], "ayse@test.edu")


class UserManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username="admin", email="admin@test.edu", password="x", role=Role.ADMIN)
        self.student = User.objects.create_user(username="ogr", email="ogr@test.edu", password="x")

    def test_student_cannot_list_or_change_users(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get("/api/users/").status_code, 403)
        res = self.client.patch(f"/api/users/{self.student.pk}/", {"role": "ADMIN"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, Role.STUDENT)

    def test_anonymous_cannot_list_users(self):
        self.assertEqual(self.client.get("/api/users/").status_code, 401)

    def test_admin_changes_role_but_not_own(self):
        self.client.force_authenticate(self.admin)
        res = self.client.patch(f"/api/users/{self.student.pk}/", {"role": "UNIT_MANAGER"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["role"], "UNIT_MANAGER")
        own = self.client.patch(f"/api/users/{self.admin.pk}/", {"role": "STUDENT"}, format="json")
        self.assertEqual(own.status_code, 400)

    def test_user_list_has_no_passwords(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/users/")
        self.assertTrue(all("password" not in u for u in res.data))
