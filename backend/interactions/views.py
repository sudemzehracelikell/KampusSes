from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import DestroyAPIView, ListCreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from reports.models import Report
from reports.services import user_manages_report

from .models import Comment, Support
from .serializers import CommentSerializer


def _visible_report(pk):
    # Gizlenen (FR-16) ve geri çekilen (FR-06) kayıtta destek ve yorum yapılamaz.
    return get_object_or_404(Report, pk=pk, is_removed=False, is_withdrawn=False)


def _ensure_open(report, action):
    if report.is_closed:
        raise PermissionDenied(f"Kapanmış bir bildirime {action}.")


class SupportView(APIView):
    """POST: destek ver, DELETE: desteği geri al."""

    permission_classes = [IsAuthenticated]

    def _response(self, report, supported):
        return Response({"support_count": report.supports.count(), "has_supported": supported})

    def post(self, request, report_pk):
        report = _visible_report(report_pk)
        _ensure_open(report, "destek verilemez")
        try:
            with transaction.atomic():
                Support.objects.create(report=report, user=request.user)
        except IntegrityError:
            return Response({"detail": "Bu bildirime zaten destek verdiniz."}, status=status.HTTP_409_CONFLICT)
        return self._response(report, True)

    def delete(self, request, report_pk):
        report = _visible_report(report_pk)
        _ensure_open(report, "ait destek geri alınamaz")
        Support.objects.filter(report=report, user=request.user).delete()
        return self._response(report, False)


class CommentListCreateView(ListCreateAPIView):
    serializer_class = CommentSerializer
    pagination_class = None

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get_queryset(self):
        return Comment.objects.filter(
            report_id=self.kwargs["report_pk"], report__is_removed=False, report__is_withdrawn=False
        ).select_related("user")

    def perform_create(self, serializer):
        report = _visible_report(self.kwargs["report_pk"])
        _ensure_open(report, "yorum yapılamaz")
        # Atanan birimin personelinin veya Admin'in yorumu resmi yanıt sayılır (FR-10).
        serializer.save(report=report, user=self.request.user, is_official=user_manages_report(self.request.user, report))


class CommentDeleteView(DestroyAPIView):
    def get_queryset(self):
        # FR-06: Geri çekilen kaydın yorumları silinemez. FR-16: Gizlenen kayda yalnızca Admin erişir.
        qs = Comment.objects.filter(report__is_withdrawn=False)
        return qs if self.request.user.is_admin_role else qs.filter(report__is_removed=False)

    def perform_destroy(self, instance):
        user = self.request.user
        if instance.user_id != user.pk and not user.is_admin_role:
            raise PermissionDenied("Yalnızca kendi yorumunuzu silebilirsiniz.")
        instance.delete()
