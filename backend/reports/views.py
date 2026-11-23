import django_filters
from django.db.models import Q
from rest_framework import mixins, parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import ReadOnlyOrAdmin

from . import services
from .models import Category, Report, ReportMedia, ReportStatus, Tag
from .serializers import (
    CategorySerializer,
    MediaUploadSerializer,
    ReassignSerializer,
    ReportDetailSerializer,
    ReportListSerializer,
    ReportMediaSerializer,
    ReportWriteSerializer,
    StatusChangeSerializer,
    TagSerializer,
)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.select_related("default_unit")
    serializer_class = CategorySerializer
    permission_classes = [ReadOnlyOrAdmin]
    pagination_class = None


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class ReportFilter(django_filters.FilterSet):
    category = django_filters.NumberFilter(field_name="category_id")
    status = django_filters.ChoiceFilter(choices=ReportStatus.choices)
    unit = django_filters.NumberFilter(field_name="assigned_unit_id")
    tag = django_filters.CharFilter(field_name="tags__name", lookup_expr="iexact")
    open = django_filters.BooleanFilter(method="filter_open")
    mine = django_filters.BooleanFilter(method="filter_mine")
    my_units = django_filters.BooleanFilter(method="filter_my_units")
    unassessed = django_filters.BooleanFilter(method="filter_unassessed")

    class Meta:
        model = Report
        fields = ["category", "status", "unit", "tag"]

    def filter_open(self, qs, name, value):
        closed = ReportStatus.closed()
        return qs.exclude(status__in=closed) if value else qs.filter(status__in=closed)

    def _user(self):
        user = getattr(self.request, "user", None)
        return user if user and user.is_authenticated else None

    def filter_mine(self, qs, name, value):
        user = self._user()
        return qs.filter(created_by=user) if value and user else qs

    def filter_my_units(self, qs, name, value):
        user = self._user()
        return qs.filter(assigned_unit__members=user) if value and user else qs

    def filter_unassessed(self, qs, name, value):
        user = self._user()
        return qs.exclude(assessments__reviewer=user) if value and user else qs


class ReportViewSet(viewsets.ModelViewSet):
    """
    Bildirimler. Okuma herkese açıktır; yazma işlemlerinin her biri kendi yetki
    kuralını uygular (sahip, birim personeli, Admin).
    """

    filterset_class = ReportFilter
    search_fields = ["title", "description", "location"]
    ordering_fields = ["created_at", "support_count", "priority_score"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        qs = Report.objects.select_related("category__default_unit", "assigned_unit", "created_by").prefetch_related("tags")
        user = self.request.user
        if not (user.is_authenticated and user.is_admin_role):
            qs = qs.filter(is_removed=False)
        if self.action == "retrieve":
            qs = qs.prefetch_related("media", "status_updates__user", "status_updates__unit")
        return services.with_priority(qs).distinct()

    def get_permissions(self):
        if self.action in {"list", "retrieve", "similar"}:
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ReportDetailSerializer
        if self.action in {"create", "partial_update"}:
            return ReportWriteSerializer
        return ReportListSerializer

    def _detail(self, report, code=status.HTTP_200_OK):
        report = self.get_queryset().get(pk=report.pk)
        return Response(ReportDetailSerializer(report, context=self.get_serializer_context()).data, status=code)

    def _check_owner_can_edit(self, report):
        user = self.request.user
        if user.is_admin_role:
            return
        if report.created_by_id != user.pk:
            raise PermissionDenied("Yalnızca bildirimin sahibi bu işlemi yapabilir.")
        if report.status not in ReportStatus.editable_by_owner():
            raise PermissionDenied("Birim işleme başladıktan sonra bildirim değiştirilemez.")

    def _check_manager(self, report):
        if not services.user_manages_report(self.request.user, report):
            raise PermissionDenied("Bu bildirimi yalnızca atandığı birimin personeli yönetebilir.")

    def _business(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs), None
        except services.BusinessRuleError as exc:
            return None, Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # --- CRUD -------------------------------------------------------------

    def create(self, request, *args, **kwargs):
        serializer = ReportWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tags = data.pop("tags", None)
        report = services.create_report(request.user, tags=tags, **data)
        return self._detail(report, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        report = self.get_object()
        self._check_owner_can_edit(report)
        serializer = ReportWriteSerializer(report, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tags = data.pop("tags", None)
        for field, value in data.items():
            setattr(report, field, value)
        report.save()
        if tags is not None:
            report.tags.set(tags)
        return self._detail(report)

    def destroy(self, request, *args, **kwargs):
        report = self.get_object()
        if request.user.is_admin_role and report.created_by_id != request.user.pk:
            # Admin uygunsuz içeriği kalıcı silmez, gizler (FR-16).
            report.is_removed = True
            report.save(update_fields=["is_removed", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        self._check_owner_can_edit(report)
        report.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # --- Ek uçlar ---------------------------------------------------------

    @action(detail=False, methods=["get"])
    def similar(self, request):
        """Aynı kategori ve konumdaki açık bildirimler."""
        reports = services.find_similar(
            request.query_params.get("category"),
            request.query_params.get("location", ""),
            exclude_id=request.query_params.get("exclude"),
        )
        return Response(ReportListSerializer(reports, many=True).data)

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        report = self.get_object()
        self._check_manager(report)
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, error = self._business(
            services.change_status, report, request.user, serializer.validated_data["status"], serializer.validated_data["note"]
        )
        return error or self._detail(report)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        report = self.get_object()
        self._check_manager(report)
        serializer = ReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, error = self._business(
            services.reassign, report, request.user, serializer.validated_data["unit"], serializer.validated_data.get("note", "")
        )
        return error or self._detail(report)

    @action(detail=True, methods=["post"], parser_classes=[parsers.MultiPartParser, parsers.FormParser])
    def media(self, request, pk=None):
        report = self.get_object()
        self._check_owner_can_edit(report)
        if report.media.count() >= 3:
            return Response({"detail": "Bir bildirime en fazla 3 dosya eklenebilir."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = MediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        media = ReportMedia.objects.create(report=report, file=serializer.validated_data["file"])
        return Response(ReportMediaSerializer(media, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ReportMediaViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = ReportMedia.objects.select_related("report")

    def perform_destroy(self, instance):
        user = self.request.user
        report = instance.report
        allowed = user.is_admin_role or (
            report.created_by_id == user.pk and report.status in ReportStatus.editable_by_owner()
        )
        if not allowed:
            raise PermissionDenied("Bu dosyayı silme yetkiniz yok.")
        instance.file.delete(save=False)
        instance.delete()
