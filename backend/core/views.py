from django.conf import settings
from django.db import connection
from django.http import FileResponse, JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Liveness for Render's health check: the app is up and the database answers. No PayPal call."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:
        return Response({"status": "error", "database": type(exc).__name__}, status=503)
    return Response({"status": "ok", "database": connection.vendor})


def spa(request):
    """The built React app. Before the first frontend build, say how to get it."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return JsonResponse({"service": "thuma", "frontend": "not built: run `npm run build` in frontend/",
                             "api": "/api/docs/"})
    return FileResponse(index.open("rb"), content_type="text/html")
