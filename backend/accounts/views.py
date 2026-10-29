"""Session auth for the SPA, plus the demo persona switcher (DEMO_MODE only)."""

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from mandates.serializers import display_name

from .models import Membership


def _me(user):
    m = Membership.objects.filter(user=user).select_related("family").order_by("created_at").first()
    return {
        "id": user.id, "username": user.username, "name": display_name(user),
        "family": {"id": str(m.family.id), "name": m.family.name} if m else None,
        "role": m.role if m else None, "country": m.country if m else "",
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def me(request):
    """Also sets the CSRF cookie the SPA sends back on every write."""
    user = request.user if request.user.is_authenticated else None
    return Response({"authenticated": user is not None, "user": _me(user) if user else None,
                     "demo_mode": settings.DEMO_MODE})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    user = authenticate(request, username=request.data.get("username", ""), password=request.data.get("password", ""))
    if user is None:
        raise ValidationError({"detail": "Wrong username or password"})
    login(request, user)
    return Response(_me(user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({"ok": True})


def _demo_users():
    if not settings.DEMO_MODE:
        raise NotFound()
    # Ordinary family members only; staff and admin accounts are never offered.
    return get_user_model().objects.filter(memberships__isnull=False, is_staff=False, is_superuser=False) \
        .distinct().order_by("date_joined")


@api_view(["GET"])
@permission_classes([AllowAny])
def demo_users(request):
    return Response([_me(u) for u in _demo_users()[:20]])


@api_view(["POST"])
@permission_classes([AllowAny])
def demo_login(request):
    user = _demo_users().filter(username=request.data.get("username", "")).first()
    if user is None:
        raise ValidationError({"detail": "No such demo user"})
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response(_me(user))
