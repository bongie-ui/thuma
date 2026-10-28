from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from core.views import health


def index(request):
    return JsonResponse({"service": "thuma", "endpoints": ["/api/health/", "/api/health/paypal/", "/admin/"]})


urlpatterns = [
    path("", index),
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/", include("payments.urls")),
]
