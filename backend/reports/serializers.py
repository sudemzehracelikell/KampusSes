from rest_framework import serializers

from accounts.serializers import PublicUserSerializer
from units.models import Unit

from .models import Category, Report, ReportMedia, ReportStatus, StatusUpdate, Tag


class CategorySerializer(serializers.ModelSerializer):
    default_unit_name = serializers.CharField(source="default_unit.name", read_only=True, default=None)

    class Meta:
        model = Category
        fields = ["id", "name", "description", "default_unit", "default_unit_name"]


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name"]


class UnitRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ["id", "name"]


class ReportMediaSerializer(serializers.ModelSerializer):
    is_image = serializers.BooleanField(read_only=True)

    class Meta:
        model = ReportMedia
        fields = ["id", "file", "is_image", "uploaded_at"]
        read_only_fields = ["id", "is_image", "uploaded_at"]


class StatusUpdateSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)
    old_status_display = serializers.SerializerMethodField()
    new_status_display = serializers.CharField(source="get_new_status_display", read_only=True)
    unit = UnitRefSerializer(read_only=True)

    class Meta:
        model = StatusUpdate
        fields = ["id", "user", "old_status", "old_status_display", "new_status", "new_status_display", "unit", "note", "created_at"]

    def get_old_status_display(self, obj):
        return ReportStatus(obj.old_status).label if obj.old_status else ""


class ReportListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    assigned_unit = UnitRefSerializer(read_only=True)
    created_by = PublicUserSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    support_count = serializers.IntegerField(read_only=True, default=0)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    board_score = serializers.FloatField(read_only=True, default=0)
    priority_score = serializers.FloatField(read_only=True, default=0)
    awaiting_assessment = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id", "title", "description", "location", "category", "tags", "status", "status_display",
            "assigned_unit", "created_by", "support_count", "comment_count", "board_score",
            "priority_score", "awaiting_assessment", "created_at", "updated_at",
        ]

    def get_awaiting_assessment(self, obj):
        """FR-15: Kurul puanı olmayan kayıtta ortalama 0 alınır ve 'Değerlendirme bekliyor' gösterilir."""
        # Puanlar 1–5 arası olduğundan ortalamanın 0 olması hiç puan verilmediği anlamına gelir.
        return not getattr(obj, "board_score", 0)


class ReportDetailSerializer(ReportListSerializer):
    media = ReportMediaSerializer(many=True, read_only=True)
    status_updates = StatusUpdateSerializer(many=True, read_only=True)
    permissions = serializers.SerializerMethodField()
    has_supported = serializers.SerializerMethodField()

    class Meta(ReportListSerializer.Meta):
        fields = ReportListSerializer.Meta.fields + [
            "media", "status_updates", "permissions", "has_supported", "is_withdrawn", "withdrawn_at",
        ]

    def _user(self):
        request = self.context.get("request")
        return request.user if request else None

    def get_has_supported(self, obj):
        user = self._user()
        return bool(user and user.is_authenticated and obj.supports.filter(user=user).exists())

    def get_permissions(self, obj):
        """Frontend'in hangi butonları göstereceğine karar vermesi için. Asıl kontrol backend'dedir."""
        from prioritization.models import Assessment

        from .services import ALLOWED_TRANSITIONS, user_manages_report

        user = self._user()
        # FR-06: Geri çekilen kayıt yalnızca okunur; hiçbir işlem butonu gösterilmez.
        authed = bool(user and user.is_authenticated) and not obj.is_withdrawn
        is_owner = authed and obj.created_by_id == user.pk
        manages = authed and user_manages_report(user, obj)
        return {
            "can_edit": bool(is_owner and obj.status in ReportStatus.editable_by_owner()) or (authed and user.is_admin_role),
            # Sahibi (Admin dahil) yalnızca Yeni/Atandı kaydını geri çeker; Admin başkasının kaydını gizler.
            "can_delete": bool(is_owner and obj.status in ReportStatus.editable_by_owner())
            or bool(authed and user.is_admin_role and not is_owner),
            "can_manage": bool(manages and not obj.is_closed),
            "allowed_transitions": sorted(ALLOWED_TRANSITIONS[obj.status]) if manages else [],
            "can_support": bool(authed and not obj.is_closed),
            "can_comment": bool(authed and not obj.is_closed),
            "can_assess": bool(authed and user.is_board_member and not obj.is_closed),
            "my_assessment": (
                Assessment.objects.filter(report=obj, reviewer=user).values("urgency", "impact", "note").first()
                if authed and user.is_board_member
                else None
            ),
        }


class ReportWriteSerializer(serializers.ModelSerializer):
    tags = serializers.ListField(child=serializers.CharField(max_length=50), required=False, write_only=True)

    class Meta:
        model = Report
        fields = ["title", "description", "location", "category", "tags"]

    def validate_title(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("Başlık en az 5 karakter olmalıdır.")
        return value

    def validate_description(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError("Açıklama en az 10 karakter olmalıdır.")
        return value

    def validate_tags(self, value):
        names = {name.strip().lower().lstrip("#") for name in value if name.strip()}
        if len(names) > 5:
            raise serializers.ValidationError("En fazla 5 etiket eklenebilir.")
        return [Tag.objects.get_or_create(name=name)[0] for name in sorted(names)]


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ReportStatus.choices)
    note = serializers.CharField(max_length=2000)


class ReassignSerializer(serializers.Serializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all())
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class MediaUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        from django.core.exceptions import ValidationError as DjangoValidationError

        from .models import validate_upload

        try:
            validate_upload(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value
