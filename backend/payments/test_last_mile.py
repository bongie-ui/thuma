from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from agent.models import ChatMessage
from agent.tests.helpers import submit
from core.testing import Fixtures
from mandates.models import LedgerEntry, Request
from payments import last_mile
from payments.management.commands.poll_payouts import poll_once
from payments.models import RailTransaction
from payments.payouts import apply_rail_status
from payments.rails import RailResult, RailStatus


class LastMileTests(TestCase):
    def setUp(self):
        self.f = Fixtures()
        self.mandate = self.f.support_mandate()

    def paid(self, product, amount="10"):
        req = submit(self.f, self.mandate, amount, product)
        tx = apply_rail_status(req.rail_transactions.get(), RailTransaction.SUCCESS)
        tx.refresh_from_db()
        return tx

    def test_bundles_delivered_after_delay(self):
        tx = self.paid("bundles")
        self.assertEqual(tx.last_mile_status, RailTransaction.DELIVERING)
        self.assertEqual(last_mile.advance(tx).last_mile_status, RailTransaction.DELIVERING)
        later = timezone.now() + timedelta(seconds=last_mile.DELIVERY_SECONDS + 1)
        tx = last_mile.advance(tx, now=later)
        self.assertEqual(tx.last_mile_status, RailTransaction.DELIVERED)
        self.assertEqual(tx.request.ledger.filter(event=LedgerEntry.DELIVERED).count(), 1)
        last_mile.advance(tx, now=later)  # idempotent
        self.assertEqual(tx.request.ledger.filter(event=LedgerEntry.DELIVERED).count(), 1)

    def test_cash_awaits_collection_with_code_and_notice(self):
        tx = self.paid("cash", "40")
        self.assertEqual(tx.last_mile_status, RailTransaction.AWAITING_COLLECTION)
        self.assertRegex(tx.collection_code, r"^\d{6}$")
        notice = ChatMessage.objects.get(linked_request=tx.request)
        self.assertEqual(notice.conversation.participant_phone, self.f.beneficiary.phone)
        self.assertIn("$40.00", notice.text)
        self.assertIn(tx.collection_code, notice.text)

    def test_collect(self):
        tx = self.paid("cash", "40")
        with self.assertRaises(ValueError):
            last_mile.collect(tx, code="000000" if tx.collection_code != "000000" else "111111")
        tx = last_mile.collect(tx, code=tx.collection_code)
        self.assertEqual(tx.last_mile_status, RailTransaction.COLLECTED)
        self.assertEqual(last_mile.collect(tx).last_mile_status, RailTransaction.COLLECTED)

    def test_cannot_collect_bundles(self):
        with self.assertRaises(ValueError):
            last_mile.collect(self.paid("bundles"))

    def test_paypal_payee_has_no_last_mile(self):
        from mandates.models import Mandate
        mandate = self.f.mandate(Mandate.VIKELA, [
            {"kind": "allowed_payees", "params": {"payee_ids": [str(self.f.supplier.id)]}},
            {"kind": "max_per_request", "params": {"amount": 100}}])
        req = submit(self.f, mandate, "20", beneficiary=None, payee=self.f.supplier)
        tx = apply_rail_status(req.rail_transactions.get(), RailTransaction.SUCCESS)
        self.assertEqual(tx.last_mile_status, RailTransaction.LAST_MILE_NA)


class PollPayoutsTests(TestCase):
    def test_poll_marks_paid_and_starts_delivery(self):
        f = Fixtures()
        req = submit(f, f.support_mandate(), "10", "bundles")
        tx = req.rail_transactions.get()
        with mock.patch("payments.rails.for_payee") as for_payee:
            for_payee.return_value.status.return_value = RailResult(
                rail="fake", reference=tx.reference, external_id=tx.external_id, status=RailStatus.SUCCEEDED,
                simulated=False, raw={"batch_status": "SUCCESS"})
            changed, _ = poll_once()
        self.assertEqual(changed, 1)
        req.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(req.status, Request.PAID)
        self.assertEqual(tx.last_mile_status, RailTransaction.DELIVERING)
