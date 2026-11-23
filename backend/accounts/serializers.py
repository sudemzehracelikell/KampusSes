from django.conf import settings
from django.contrib.auth import password_validation
from rest_framework import serializers

from .models import Role, User


class UserSerializer(serializers.ModelSerializer):
    """Kullanıcının kendisi ve Admin için. Parola hiçbir zaman döndürülmez."""

    role_display = serializers.CharField(source="get_role_display", read_only=True)
    unit_ids = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "role_display", "unit_ids", "date_joined"]
        read_only_fields = fields

    def get_unit_ids(self, obj):
        return list(obj.units.values_list("id", flat=True))


class PublicUserSerializer(serializers.ModelSerializer):
    """Diğer kullanıcılara gösterilen bilgi: e-posta gizlenir."""

    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "role", "role_display"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def validate_email(self, value):
        value = value.strip().lower()
        domains = getattr(settings, "ALLOWED_EMAIL_DOMAINS", [])
        if domains and value.split("@")[-1] not in domains:
            raise serializers.ValidationError(
                "Yalnızca üniversite e-posta adresleriyle kayıt olunabilir: " + ", ".join(domains)
            )
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Bu e-posta adresiyle kayıtlı bir hesap var.")
        return value

    def validate(self, attrs):
        candidate = User(username=attrs.get("username"), email=attrs.get("email"))
        password_validation.validate_password(attrs["password"], user=candidate)
        return attrs

    def create(self, validated_data):
        # Kayıt olan herkes Öğrenci rolüyle başlar; rolü yalnızca Admin değiştirir.
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            role=Role.STUDENT,
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class RoleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["role"]
