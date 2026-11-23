from rest_framework import serializers

from accounts.serializers import PublicUserSerializer

from .models import Comment


class CommentSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "text", "is_official", "user", "created_at", "can_delete"]
        read_only_fields = ["id", "is_official", "user", "created_at", "can_delete"]

    def validate_text(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Yorum boş olamaz.")
        if len(value) > 1000:
            raise serializers.ValidationError("Yorum en fazla 1000 karakter olabilir.")
        return value

    def get_can_delete(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        return bool(user and user.is_authenticated and (obj.user_id == user.pk or user.is_admin_role))
