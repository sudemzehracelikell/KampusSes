from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from rest_framework import filters, mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import User
from .permissions import IsAdminRole
from .serializers import LoginSerializer, RegisterSerializer, RoleUpdateSerializer, UserSerializer

GENERIC_LOGIN_ERROR = "E-posta veya parola hatalı."


def _failed_key(email):
    return f"login-failed:{email}"


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """
    Kimlik doğrulama sunucu tarafında yapılır.
    Art arda LOGIN_MAX_FAILED_ATTEMPTS hatalı denemeden sonra hesap geçici olarak kilitlenir.
    """
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data["email"].strip().lower()
    password = serializer.validated_data["password"]

    failed = cache.get(_failed_key(email), 0)
    if failed >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
        minutes = settings.LOGIN_LOCKOUT_SECONDS // 60
        return Response(
            {"detail": f"Çok fazla hatalı deneme. Lütfen {minutes} dakika sonra tekrar deneyin."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = authenticate(request, email=email, password=password)
    if user is None:
        cache.set(_failed_key(email), failed + 1, settings.LOGIN_LOCKOUT_SECONDS)
        # Hangi alanın hatalı olduğu söylenmez.
        return Response({"detail": GENERIC_LOGIN_ERROR}, status=status.HTTP_400_BAD_REQUEST)

    cache.delete(_failed_key(email))
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": UserSerializer(user).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)


class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Kullanıcı ve rol yönetimi — yalnızca Admin."""

    queryset = User.objects.order_by("username")
    permission_classes = [IsAdminRole]
    filter_backends = [filters.SearchFilter]
    search_fields = ["username", "email"]
    http_method_names = ["get", "patch", "delete"]
    pagination_class = None

    def get_serializer_class(self):
        if self.action == "partial_update":
            return RoleUpdateSerializer
        return UserSerializer

    def partial_update(self, request, *args, **kwargs):
        user = self.get_object()
        if user == request.user:
            return Response({"detail": "Kendi rolünüzü değiştiremezsiniz."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = RoleUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(user).data)

    def destroy(self, request, *args, **kwargs):
        if self.get_object() == request.user:
            return Response({"detail": "Kendi hesabınızı silemezsiniz."}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)
