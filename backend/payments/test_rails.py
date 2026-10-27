from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from .rails import Payee, RailError, RailStatus, available_rails, get_rail
from .rails.paypal import PayPalPayoutRail
from .rails.simulated import SimulatedBillerRail, SimulatedMobileMoneyRail

GOGO = Payee("Gogo Ncube", "263770000000")
HARDWARE = Payee("Gwanda Hardware", "hardware@example.com")


class FakeClock:
    def __init__(self, now=1_000_000):
        self.now = now

    def __call__(self):
        return self.now


class RouterTests(SimpleTestCase):
    def test_lookup(self):
        self.assertIsInstance(get_rail("paypal_payouts"), PayPalPayoutRail)
        self.assertTrue(available_rails()["biller"]["simulated"])
        self.assertFalse(available_rails()["paypal_payouts"]["simulated"])

    def test_unknown_rail(self):
        with self.assertRaises(RailError):
            get_rail("cash_in_envelope")


class SimulatedRailTests(SimpleTestCase):
    def test_pending_then_succeeded(self):
        clock = FakeClock()
        rail = SimulatedMobileMoneyRail(clock=clock)
        result = rail.pay(GOGO, Decimal("40.00"), "ref-1")
        self.assertEqual(result.status, RailStatus.PENDING)
        self.assertTrue(result.simulated)
        self.assertEqual(rail.status(result.external_id).status, RailStatus.PENDING)
        clock.now += rail.settle_seconds
        self.assertEqual(rail.status(result.external_id).status, RailStatus.SUCCEEDED)

    def test_rejects_bad_amounts(self):
        rail = SimulatedBillerRail()
        for bad in ("0", "-5", "1.234"):
            with self.assertRaises(RailError):
                rail.pay(GOGO, Decimal(bad), "ref")

    def test_rejects_other_rails_reference(self):
        ref = SimulatedMobileMoneyRail().pay(GOGO, Decimal("1"), "r").external_id
        with self.assertRaises(RailError):
            SimulatedBillerRail().status(ref)


class PayPalPayoutRailTests(SimpleTestCase):
    def test_pay_maps_batch_status(self):
        client = mock.Mock()
        client.create_payout.return_value = {
            "batch_header": {"payout_batch_id": "BATCH1", "batch_status": "PENDING"}
        }
        result = PayPalPayoutRail(client).pay(HARDWARE, Decimal("120.50"), "thuma-akha-1")
        client.create_payout.assert_called_once()
        self.assertEqual(client.create_payout.call_args.kwargs["receiver_email"], "hardware@example.com")
        self.assertEqual(result.external_id, "BATCH1")
        self.assertEqual(result.status, RailStatus.PENDING)
        self.assertFalse(result.simulated)

    def test_status_success(self):
        client = mock.Mock()
        client.get_payout_batch.return_value = {
            "batch_header": {"payout_batch_id": "BATCH1", "batch_status": "SUCCESS",
                             "sender_batch_header": {"sender_batch_id": "thuma-akha-1"}}
        }
        result = PayPalPayoutRail(client).status("BATCH1")
        self.assertEqual(result.status, RailStatus.SUCCEEDED)
        self.assertEqual(result.reference, "thuma-akha-1")
