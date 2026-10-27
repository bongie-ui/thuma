from rest_framework.decorators import api_view
from rest_framework.response import Response

from .paypal_client import PayPalError, get_client


@api_view(["GET"])
def paypal_health(request):
    """Reports whether we can authenticate against PayPal. Never returns the token itself."""
    client = get_client()
    base = {"environment": "sandbox" if client.is_sandbox else "live", "base_url": client.base_url}
    if not client.is_configured:
        return Response({**base, "status": "not_configured",
                         "detail": "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env"}, status=503)
    try:
        client.get_access_token()
    except PayPalError as exc:
        return Response({**base, "status": "error", "detail": str(exc),
                         "paypal_status": exc.status_code}, status=502)
    return Response({**base, "status": "connected"})
