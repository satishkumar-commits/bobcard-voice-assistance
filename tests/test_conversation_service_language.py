import unittest
from pathlib import Path


class ConversationServiceLanguageGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = Path("app/services/conversation_service.py").read_text(encoding="utf-8")

    def test_prompt_language_not_hardcoded_to_hindi(self) -> None:
        self.assertIn("def _prompt_language(call: Call) -> str:", self.source)
        self.assertIn("return normalize_language(call.language)", self.source)
        self.assertNotIn('def _prompt_language(call: Call) -> str:\n        return "hi-IN"', self.source)

    def test_personalized_greeting_does_not_force_hindi(self) -> None:
        self.assertIn("language_code = normalize_language(language or call.language)", self.source)
        self.assertNotIn('language_code = "hi-IN"', self.source)

    def test_consent_granted_identity_prompt_uses_active_language(self) -> None:
        self.assertIn("active_language = self._prompt_language(call)", self.source)
        self.assertIn("build_identity_verification_prompt(name=forced_customer_name, language=active_language)", self.source)
        self.assertNotIn("build_identity_verification_prompt(name=forced_customer_name, language=\"hi-IN\")", self.source)

    def test_opening_greeting_is_not_trimmed_to_two_sentences(self) -> None:
        self.assertIn('outcome="opening-greeting"', self.source)
        self.assertIn('if outcome == "opening-greeting":', self.source)
        self.assertIn("sentence_limit = 5", self.source)

    def test_terminal_outcome_skips_repeat_suppression(self) -> None:
        self.assertIn('if outcome == "escalation-requested" or business_state == CONFIRMATION_CLOSING:', self.source)

    def test_gemini_reply_preserves_full_text_for_audit(self) -> None:
        self.assertIn("preserve_full_text: bool = False", self.source)
        self.assertIn('outcome="gemini-response"', self.source)
        self.assertIn("preserve_full_text=True", self.source)

    def test_link_request_has_deterministic_restart_route(self) -> None:
        self.assertIn('if response_plan["route"] == "link_restart_guidance":', self.source)
        self.assertIn("build_process_restart_link_reply(prompt_language)", self.source)


if __name__ == "__main__":
    unittest.main()
