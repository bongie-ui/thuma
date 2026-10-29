"""Update pending payouts without webhooks (local development, or a webhook fallback)."""

import time

from django.core.management.base import BaseCommand

from payments import last_mile, rails
from payments.models import RailTransaction
from payments.payouts import refresh


def poll_once():
    changed = 0
    for tx in RailTransaction.objects.filter(status=RailTransaction.PENDING).exclude(external_id="") \
            .select_related("request__payee"):
        try:
            _tx, updated = refresh(tx)
        except rails.RailError as exc:
            print(f"{tx.reference}: {exc}")
            continue
        changed += updated
    delivered = sum(1 for tx in last_mile.advance_all() if tx.last_mile_status == RailTransaction.DELIVERED)
    return changed, delivered


class Command(BaseCommand):
    help = "Poll rails for pending payouts and advance the simulated last mile."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="keep polling")
        parser.add_argument("--interval", type=int, default=10, help="seconds between polls with --watch")

    def handle(self, *args, watch=False, interval=10, **options):
        while True:
            changed, delivered = poll_once()
            self.stdout.write(f"{changed} payout(s) updated, {delivered} delivery(ies) completed")
            if not watch:
                return
            time.sleep(interval)
