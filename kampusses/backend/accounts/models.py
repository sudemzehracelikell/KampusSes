from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    STUDENT = "STUDENT", "Öğrenci"
    UNIT_MANAGER = "UNIT_MANAGER", "Birim Sorumlusu"
    BOARD_MEMBER = "BOARD_MEMBER", "Kurul Üyesi"
    ADMIN = "ADMIN", "Admin"


class User(AbstractUser):
    """
    Django'nun yerleşik kullanıcı modeli genişletilir. Böylece parolalar
    özetlenerek saklanır
    """

    email = models.EmailField("e-posta", unique=True)
    role = models.CharField("rol", max_length=20, choices=Role.choices, default=Role.STUDENT)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = "kullanıcı"
        verbose_name_plural = "kullanıcılar"

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN

    @property
    def is_unit_manager(self):
        return self.role == Role.UNIT_MANAGER

    @property
    def is_board_member(self):
        return self.role == Role.BOARD_MEMBER

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
