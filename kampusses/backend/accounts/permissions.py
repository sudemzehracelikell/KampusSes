from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role


class IsAdminRole(BasePermission):
    message = "Bu işlem için Admin yetkisi gerekir."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.ADMIN)


class IsBoardMember(BasePermission):
    message = "Bu işlem yalnızca Kurul Üyeleri içindir."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.BOARD_MEMBER)


class ReadOnlyOrAdmin(BasePermission):
    """Okuma herkese açık, yazma yalnızca Admin."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.ADMIN)
