from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts import views as account_views
from interactions import views as interaction_views
from prioritization.views import AssessmentView
from reports import views as report_views
from units.views import UnitViewSet

router = DefaultRouter()
router.register("users", account_views.UserViewSet, basename="user")
router.register("units", UnitViewSet, basename="unit")
router.register("categories", report_views.CategoryViewSet, basename="category")
router.register("tags", report_views.TagViewSet, basename="tag")
router.register("reports", report_views.ReportViewSet, basename="report")
router.register("media", report_views.ReportMediaViewSet, basename="media")

api_patterns = [
    path("auth/register/", account_views.register, name="register"),
    path("auth/login/", account_views.login, name="login"),
    path("auth/logout/", account_views.logout, name="logout"),
    path("auth/me/", account_views.me, name="me"),
    path("reports/<int:report_pk>/support/", interaction_views.SupportView.as_view(), name="report-support"),
    path("reports/<int:report_pk>/comments/", interaction_views.CommentListCreateView.as_view(), name="report-comments"),
    path("comments/<int:pk>/", interaction_views.CommentDeleteView.as_view(), name="comment-delete"),
    path("reports/<int:report_pk>/assessment/", AssessmentView.as_view(), name="report-assessment"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_patterns)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
