from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsBoardMember
from reports.models import Report

from .models import Assessment


class AssessmentSerializer(serializers.ModelSerializer):
    urgency = serializers.IntegerField(min_value=1, max_value=5)
    impact = serializers.IntegerField(min_value=1, max_value=5)

    class Meta:
        model = Assessment
        fields = ["urgency", "impact", "note", "updated_at"]
        read_only_fields = ["updated_at"]


class AssessmentView(APIView):
    """
    GET: kurul üyesinin bu bildirime verdiği puan.
    PUT: puan ver veya güncelle — bir üye, bir bildirim, bir puan.
    """

    permission_classes = [IsBoardMember]

    def get(self, request, report_pk):
        assessment = Assessment.objects.filter(report_id=report_pk, reviewer=request.user).first()
        if not assessment:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(AssessmentSerializer(assessment).data)

    def put(self, request, report_pk):
        report = get_object_or_404(Report, pk=report_pk, is_removed=False)
        if report.is_closed:
            raise PermissionDenied("Kapanmış bildirimler değerlendirilemez.")
        serializer = AssessmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assessment, created = Assessment.objects.update_or_create(
            report=report, reviewer=request.user, defaults=serializer.validated_data
        )
        return Response(
            AssessmentSerializer(assessment).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )
