"""Shared helpers for the REST API: the caller's family, and ServiceError -> 400."""

from django.core.exceptions import ValidationError
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from accounts.models import Membership
from mandates.services import ServiceError


def current_membership(request):
    """The caller's membership. A user in several families uses the oldest one (family switching is not built)."""
    m = Membership.objects.filter(user=request.user).select_related("family").order_by("created_at").first()
    if m is None:
        raise PermissionDenied("You are not a member of any family")
    return m


def current_family(request):
    return current_membership(request).family


def get_or_404(queryset, **lookup):
    """Missing rows and malformed ids are both a 404."""
    try:
        return queryset.get(**lookup)
    except (queryset.model.DoesNotExist, ValueError, ValidationError):
        raise NotFound()


class IsFamilyMember(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and Membership.objects.filter(user=request.user).exists()


def exception_handler(exc, context):
    """Service rule violations are the caller's problem: 400 with a message safe to show."""
    if isinstance(exc, ServiceError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return drf_exception_handler(exc, context)
