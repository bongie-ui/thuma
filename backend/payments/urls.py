from django.urls import path

from . import views

urlpatterns = [
    path("health/paypal/", views.paypal_health, name="paypal-health"),
]
