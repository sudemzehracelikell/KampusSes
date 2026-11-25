from rest_framework import serializers

from accounts.serializers import PublicUserSerializer

from .models import Unit


class UnitSerializer(serializers.ModelSerializer):
    members = PublicUserSerializer(many=True, read_only=True)
    open_report_count = serializers.SerializerMethodField()

    class Meta:
        model = Unit
        fields = ["id", "name", "description", "members", "open_report_count", "created_at"]
        read_only_fields = ["id", "members", "open_report_count", "created_at"]

    def get_open_report_count(self, obj):
        from reports.models import ReportStatus

        reports = obj.reports.filter(is_removed=False, is_withdrawn=False)
        return reports.exclude(status__in=ReportStatus.closed()).count()


class MemberSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
