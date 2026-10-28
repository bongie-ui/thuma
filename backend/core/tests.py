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
