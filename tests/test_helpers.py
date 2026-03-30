import unittest

from app.utils.helpers import enforce_devanagari_hindi_reply


class HelpersTests(unittest.TestCase):
    def test_preserves_name_after_namaste(self) -> None:
        text = "नमस्ते Satish। मैं माया हूँ।"
        normalized = enforce_devanagari_hindi_reply(text)
        self.assertIn("Satish", normalized)

    def test_preserves_name_before_ji(self) -> None:
        text = "क्या मैं Satish जी से बात कर रही हूँ? कृपया हाँ या नहीं कहिए।"
        normalized = enforce_devanagari_hindi_reply(text)
        self.assertIn("Satish जी", normalized)


if __name__ == "__main__":
    unittest.main()
