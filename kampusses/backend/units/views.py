from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import Role, User
from accounts.permissions import IsAdminRole, ReadOnlyOrAdmin

from .models import Unit
from .serializers import MemberSerializer, UnitSerializer


class UnitViewSet(viewsets.ModelViewSet):
    """Birimler herkese görünür; oluşturma, düzenleme ve personel yönetimi Admin'e aittir."""

    queryset = Unit.objects.prefetch_related("members")
    serializer_class = UnitSerializer
    permission_classes = [ReadOnlyOrAdmin]
    pagination_class = None
    search_fields = ["name"]

    @action(detail=True, methods=["post"], permission_classes=[IsAdminRole])
    def members(self, request, pk=None):
        unit = self.get_object()
        serializer = MemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_object_or_404(User, pk=serializer.validated_data["user_id"])
        if user.role != Role.UNIT_MANAGER:
            return Response(
                {"detail": "Birime yalnızca Birim Sorumlusu rolündeki kullanıcılar eklenebilir."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        unit.members.add(user)
        return Response(UnitSerializer(unit).data)

    @action(detail=True, methods=["delete"], url_path=r"members/(?P<user_id>\d+)", permission_classes=[IsAdminRole])
    def remove_member(self, request, pk=None, user_id=None):
        unit = self.get_object()
        unit.members.remove(get_object_or_404(User, pk=user_id))
        return Response(UnitSerializer(unit).data)
