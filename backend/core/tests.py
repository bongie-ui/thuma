from django.test import SimpleTestCase, TestCase, override_settings

from .phones import find_phones, normalize_phone


@override_settings(DEFAULT_PHONE_COUNTRY_CODE="263")
class PhoneTests(SimpleTestCase):
    def test_normalize(self):
        self.assertEqual(normalize_phone("0771234567"), "+263771234567")
        self.assertEqual(normalize_phone("+263 77 123 4567"), "+263771234567")
        self.assertEqual(normalize_phone("00447700900123"), "+447700900123")
        self.assertIsNone(normalize_phone("12"))
        self.assertIsNone(normalize_phone(""))

    def test_find_phones_ignores_amounts_and_codes(self):
        text = "Please send $150 to 0771234567 or 077-123-4568, code 482193, ref 2026"
        self.assertEqual(find_phones(text), ["+263771234567", "+263771234568"])

    def test_find_phones_international(self):
        self.assertEqual(find_phones("call me on +27 82 555 0100"), ["+27825550100"])


class HealthTests(TestCase):
    def test_health(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class SeedDemoTests(TestCase):
    """The seed must produce valid, signed, funded mandates and be safely re-runnable."""

    def test_seed_and_reset(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from mandates import services, signing
        from mandates.models import Mandate, Request

        call_command("seed_demo", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", "--reset", stdout=StringIO())

        mandates = list(Mandate.objects.all())
        self.assertEqual(len(mandates), 3)
        for m in mandates:
            self.assertTrue(signing.verify(m))
            self.assertGreater(services.mandate_balance(m), 0)
        history = Request.objects.filter(status=Request.PAID)
        self.assertGreaterEqual(history.count(), 3)  # AMOUNT_SPIKE needs a baseline
        self.assertFalse(history.filter(created_at__gte=services.timezone.now().replace(day=1)).exists())
