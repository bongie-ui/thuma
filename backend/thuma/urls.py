from django.contrib import admin
from django.urls import include, path, re_path

from core.views import spa

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("thuma.api_urls")),
    # Everything else is the React app (client-side routes included).
    re_path(r"^(?!api/|admin/|static/).*$", spa),
]
