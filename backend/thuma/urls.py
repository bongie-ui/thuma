from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def index(request):
    return JsonResponse({"service": "thuma", "endpoints": ["/api/health/paypal/", "/admin/"]})


urlpatterns = [
    path("", index),
    path("admin/", admin.site.urls),
    path("api/", include("payments.urls")),
]
