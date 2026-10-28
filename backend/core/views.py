from django.db import connection
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def health(request):
    """Liveness for Render's health check: the app is up and the database answers. No PayPal call."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:
        return Response({"status": "error", "database": type(exc).__name__}, status=503)
    return Response({"status": "ok", "database": connection.vendor})
