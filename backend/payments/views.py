from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api import IsFamilyMember, current_family, get_or_404

from . import last_mile
from .models import RailTransaction
from .paypal_client import PayPalError, get_client


@api_view(["GET"])
@permission_classes([AllowAny])
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


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def fund_create_order(request, pk):
    """PayPal Orders checkout. Phase 4 builds it with the APIMatic PayPal Server SDK (CLAUDE.md rule 5)."""
    get_or_404(current_family(request).mandates, pk=pk)
    return Response({"detail": "Funding with PayPal is not switched on yet."}, status=503)


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def fund_capture(request, pk):
    get_or_404(current_family(request).mandates, pk=pk)
    return Response({"detail": "Funding with PayPal is not switched on yet."}, status=503)


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def demo_collect(request, pk):
    """Demo button: the beneficiary collects cash at an agent (simulated last mile)."""
    if not settings.DEMO_MODE:
        raise NotFound()
    tx = get_or_404(RailTransaction.objects.filter(request__mandate__family=current_family(request)), pk=pk)
    try:
        tx = last_mile.collect(tx, code=request.data.get("code") or None)
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)})
    return Response({"id": str(tx.id), "last_mile_status": tx.last_mile_status})
