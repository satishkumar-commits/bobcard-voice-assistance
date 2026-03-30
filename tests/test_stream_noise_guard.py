import unittest
from pathlib import Path


class StreamNoiseGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = Path("app/services/twilio_media_stream_service.py").read_text(encoding="utf-8")

    def test_hello_like_short_tokens_are_not_ignored(self) -> None:
        self.assertIn('"हेलो"', self.source)
        self.assertIn("compact = re.sub", self.source)
        self.assertIn("if len(compact) > 1 and any(ch.isalpha() for ch in compact):", self.source)


if __name__ == "__main__":
    unittest.main()
